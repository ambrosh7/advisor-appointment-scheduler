"""Phase 7: voice pipeline uses same handle(); IST verbatim; code spelled; barge-in."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.voice

from api.chat.app import create_app as create_chat_app
from api.voice.app import create_app as create_voice_app
from domain.calendar import MockCalendarService
from domain.clock import FixedClock
from domain.codes import to_spelling
from integrations.booking_agent.execute import ExecuteBookingSideEffects
from integrations.booking_agent.gemini_agent import (
    GeminiBookingAgent,
    scripted_gemini_success_sequence,
)
from integrations.google_mcp.config import GoogleMcpConfig
from integrations.google_mcp.hybrid_tools import HybridBookingTools
from integrations.google_mcp.tools import GoogleMcpTools
from integrations.voice.audio_io import MemoryAudioIO
from integrations.voice.pipeline import VoicePipeline
from integrations.voice.stt import PassthroughSpeechToText
from integrations.voice.tts import RecordingTextToSpeech
from nlu.engine import RuleNluEngine
from session.orchestrator import Orchestrator
from session.states import State
from session.store import InMemorySessionStore
from tests.support.recording_google import make_recording_clients


def _config() -> GoogleMcpConfig:
    return GoogleMcpConfig(
        gemini_api_key="test-key",
        gemini_model="gemini-3.8-flash",
        calendar_id="primary",
        docs_prebooking_id="doc-prebook-1",
        gmail_advisor_to="advisor@example.com",
        secure_link_template="https://example.com/complete?ref={code}",
        oauth_client_secrets=Path("credentials.json"),
        oauth_token_path=Path("token.json"),
        service_account_file=Path(""),
        mcp_server_url="https://example.railway.app/mcp",
        mcp_bearer_token="test-token",
    )


class _FakeRemote:
    def call_tool(self, name: str, arguments: dict):
        return {"content": [{"type": "text", "text": f"ok:{name}"}]}


def _orch_with_booking():
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))
    config = _config()
    clients = make_recording_clients()
    tools = HybridBookingTools(
        local_calendar=GoogleMcpTools(clients, config),
        remote=_FakeRemote(),  # type: ignore[arg-type]
        config=config,
    )

    class _Agent:
        def execute(self, request):
            return GeminiBookingAgent(
                tools=tools,
                config=config,
                generate_content=scripted_gemini_success_sequence(request, config),
            ).execute(request)

    orch = Orchestrator(
        session_store=InMemorySessionStore(),
        calendar=MockCalendarService(),
        nlu=RuleNluEngine(clock=clock),
        clock=clock,
        booking_side_effects=ExecuteBookingSideEffects(_Agent()),
        google_config=config,
    )
    return orch


def test_e2e_voice_happy_path_ist_and_spelled_code() -> None:
    orch = _orch_with_booking()
    tts = RecordingTextToSpeech()
    vp = VoicePipeline(
        orch,
        stt=PassthroughSpeechToText(),
        tts=tts,
        audio_io=MemoryAudioIO(),
        spell_booking_codes=True,
    )

    assert vp.start_session().state is State.DISCLAIMER_AWAIT_ACK
    assert vp.commit_utterance("yes").state is State.COLLECT_NAME
    assert vp.commit_utterance("Ambrosh Patel").state is State.INTENT_ROUTING
    assert vp.commit_utterance("book new").state is State.BOOK_TOPIC
    assert vp.commit_utterance("topic kyc").state is State.BOOK_TIME_PREFERENCE
    offer = vp.commit_utterance("time monday afternoon")
    assert offer.state is State.BOOK_OFFER_SLOTS
    # Slot choice uses same NLU as typing “first”
    confirm = vp.commit_utterance("first")
    assert confirm.state is State.BOOK_CONFIRM
    confirm_blob = "\n".join(confirm.spoken_messages)
    assert "IST" in confirm_blob
    assert "2026" in confirm_blob

    done = vp.commit_utterance("confirm")
    assert done.state is State.CLOSE
    spoken = "\n".join(done.spoken_messages)
    chat = "\n".join(done.messages)
    assert "Booking code:" in chat
    # Raw code in chat; spelled form in TTS spoken path
    code = None
    for line in chat.splitlines():
        if "Booking code:" in line:
            code = line.split(":", 1)[1].strip()
            break
    assert code
    assert to_spelling(code) in spoken
    assert done.latency.total_ms >= 0
    assert done.audio_bytes_played > 0


def test_websocket_text_utterance_roundtrip() -> None:
    orch = _orch_with_booking()
    client = TestClient(create_voice_app(orch))
    with client.websocket_connect("/ws/voice") as ws:
        ws.send_json({"type": "start"})
        started = ws.receive_json()
        assert started["type"] == "session_started"
        assert started["state"] == "DISCLAIMER_AWAIT_ACK"
        assert "latency_ms" in started

        ws.send_json({"type": "text_utterance", "text": "I understand"})
        final = ws.receive_json()
        assert final["type"] == "final_transcript"
        assert final["text"] == "I understand"
        turn = ws.receive_json()
        assert turn["type"] == "assistant_turn"
        assert turn["state"] == "COLLECT_NAME"
        ws.send_json({"type": "text_utterance", "text": "Ambrosh Patel"})
        final2 = ws.receive_json()
        assert final2["type"] == "final_transcript"
        turn2 = ws.receive_json()
        assert turn2["type"] == "assistant_turn"
        assert turn2["state"] == "INTENT_ROUTING"

        ws.send_json({"type": "speech_start"})
        cancelled = ws.receive_json()
        assert cancelled["type"] == "tts_cancelled"


@pytest.mark.voice
def test_chat_suite_baseline_still_works_alongside_voice() -> None:
    """Chat HTTP path unchanged — voice is an I/O adapter only."""
    orch = _orch_with_booking()
    c = TestClient(create_chat_app(orch))
    sid = c.post("/session").json()["session_id"]

    def say(text: str) -> dict:
        return c.post(f"/session/{sid}/message", json={"text": text}).json()

    assert say("yes")["state"] == "COLLECT_NAME"
    assert say("Ambrosh Patel")["state"] == "INTENT_ROUTING"
    assert say("book new")["state"] == "BOOK_TOPIC"
    assert say("topic kyc")["state"] == "BOOK_TIME_PREFERENCE"
    assert say("time monday afternoon")["state"] == "BOOK_OFFER_SLOTS"
    assert say("1")["state"] == "BOOK_CONFIRM"
    done = say("confirm")
    assert done["state"] == "CLOSE"
    assert any("Booking code:" in m for m in done["messages"])
