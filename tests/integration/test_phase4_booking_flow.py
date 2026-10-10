"""Chat happy path: Gemini → hybrid tools (local Calendar + remote Docs/Gmail)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from api.chat.app import create_app
from domain.calendar import MockCalendarService
from domain.clock import FixedClock
from integrations.booking_agent.execute import ExecuteBookingSideEffects
from integrations.booking_agent.gemini_agent import (
    GeminiBookingAgent,
    scripted_gemini_success_sequence,
)
from integrations.google_mcp.config import GoogleMcpConfig
from integrations.google_mcp.hybrid_tools import HybridBookingTools
from integrations.google_mcp.tools import GoogleMcpTools
from nlu.engine import RuleNluEngine
from session.orchestrator import Orchestrator
from session.store import InMemorySessionStore
from tests.support.recording_google import make_recording_clients


def _config() -> GoogleMcpConfig:
    return GoogleMcpConfig(
        gemini_api_key="test-key",
        gemini_model="gemini-2.0-flash",
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
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": f"ok:{name}"}]}


def _orch_with_scripted_gemini():
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))
    config = _config()
    clients = make_recording_clients()
    remote = _FakeRemote()
    tools = HybridBookingTools(
        local_calendar=GoogleMcpTools(clients, config),
        remote=remote,  # type: ignore[arg-type]
        config=config,
    )

    class _Agent:
        def execute(self, request):
            agent = GeminiBookingAgent(
                tools=tools,
                config=config,
                generate_content=scripted_gemini_success_sequence(request, config),
            )
            return agent.execute(request)

    orch = Orchestrator(
        session_store=InMemorySessionStore(),
        calendar=MockCalendarService(),
        nlu=RuleNluEngine(clock=clock),
        clock=clock,
        booking_side_effects=ExecuteBookingSideEffects(_Agent()),
        google_config=config,
    )
    return orch, clients, remote


def test_api_book_new_runs_mcp_and_closes() -> None:
    orch, clients, remote = _orch_with_scripted_gemini()
    c = TestClient(create_app(orch))

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
    assert any("example.com/complete?ref=" in m for m in done["messages"])

    debug = c.get(f"/session/{sid}").json()
    assert debug["calendar_event_id"] == "evt-1"
    assert debug["mcp_tool_trace"] == [
        "calendar_create_hold",
        "docs_append_prebooking",
        "gmail_create_draft",
    ]
    assert len(clients.calendar.events_created) == 1
    assert [n for n, _ in remote.calls] == [
        "google_docs_append_text",
        "gmail_send_email",
    ]
