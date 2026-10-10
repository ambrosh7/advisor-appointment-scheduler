"""VoicePipeline barge-in and utterance commit around Orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain.calendar import MockCalendarService
from domain.clock import FixedClock
from integrations.voice.audio_io import MemoryAudioIO
from integrations.voice.pipeline import VoicePipeline
from integrations.voice.stt import PassthroughSpeechToText
from integrations.voice.tts import RecordingTextToSpeech
from nlu.engine import RuleNluEngine
from session.orchestrator import Orchestrator
from session.states import State
from session.store import InMemorySessionStore

pytestmark = pytest.mark.voice


def _pipeline() -> VoicePipeline:
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))
    orch = Orchestrator(
        session_store=InMemorySessionStore(),
        calendar=MockCalendarService(),
        nlu=RuleNluEngine(clock=clock),
        clock=clock,
    )
    return VoicePipeline(
        orch,
        stt=PassthroughSpeechToText(),
        tts=RecordingTextToSpeech(),
        audio_io=MemoryAudioIO(),
    )


def test_start_and_commit_matches_chat_states() -> None:
    vp = _pipeline()
    opened = vp.start_session()
    assert opened.state is State.DISCLAIMER_AWAIT_ACK
    assert opened.messages
    turn = vp.commit_utterance("I understand")
    assert turn.state is State.COLLECT_NAME
    turn = vp.commit_utterance("Ambrosh Patel")
    assert turn.state is State.INTENT_ROUTING
    assert turn.final_transcript == "Ambrosh Patel"
    assert turn.latency.total_ms >= 0


def test_barge_in_cancels_tts_without_state_rollback() -> None:
    vp = _pipeline()
    vp.start_session()
    state_before = vp.session.state if vp.session else None
    vp._speaking = True  # noqa: SLF001 — simulate mid-playback
    vp.feed_audio(b"hello")
    assert vp.tts.cancelled
    assert vp.session is not None
    assert vp.session.state is state_before


def test_partial_then_finalize_from_pcm_utf8() -> None:
    vp = _pipeline()
    vp.start_session()
    vp.commit_utterance("yes")
    vp.commit_utterance("Ambrosh Patel")
    partial = vp.feed_audio(b"book ")
    assert partial == "book "
    partial = vp.feed_audio(b"new")
    assert partial == "book new"
    turn = vp.commit_utterance()
    assert turn.final_transcript == "book new"
    assert turn.state is State.BOOK_TOPIC
