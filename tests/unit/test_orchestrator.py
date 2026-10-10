"""Phase 2/5 orchestrator: greet → confirm; empty calendar → waitlist."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from domain.calendar import MockCalendarService
from domain.clock import FixedClock
from domain.enums import BookingStatus
from integrations.booking_agent.waitlist import ExecuteWaitlistSideEffects
from integrations.google_mcp.config import GoogleMcpConfig
from nlu.pii import PII_REDIRECT_MESSAGE
from nlu.engine import RuleNluEngine
from session.orchestrator import Orchestrator
from session.states import State
from session.store import InMemorySessionStore


def _orch(calendar: Optional[MockCalendarService] = None) -> Orchestrator:
    # Fixed: Monday 6 Apr 2026 02:00 UTC
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))
    return Orchestrator(
        session_store=InMemorySessionStore(),
        calendar=calendar or MockCalendarService(),
        nlu=RuleNluEngine(clock=clock),
        clock=clock,
    )


def _happy_path_to_confirm(orch: Orchestrator):
    open_turn = orch.create_session()
    session = orch.store.get(open_turn.session_id)
    assert session is not None
    assert open_turn.state is State.DISCLAIMER_AWAIT_ACK
    assert any("not investment advice" in m.lower() for m in open_turn.messages)

    t = orch.handle("I understand", session)
    assert t.state is State.COLLECT_NAME
    t = orch.handle("Ambrosh Patel", session)
    assert t.state is State.INTENT_ROUTING

    t = orch.handle("book new", session)
    assert t.state is State.BOOK_TOPIC

    t = orch.handle("topic kyc", session)
    assert t.state is State.BOOK_TIME_PREFERENCE
    assert session.preference.topic is not None

    t = orch.handle("time monday afternoon", session)
    assert t.state is State.BOOK_OFFER_SLOTS
    assert len(session.offered_slots) == 2
    assert "1." in t.messages[-1]

    t = orch.handle("first", session)
    assert t.state is State.BOOK_CONFIRM
    assert session.selected_slot is not None
    assert "confirm" in t.messages[-1].lower()
    return session, t


def test_happy_path_reaches_book_confirm() -> None:
    orch = _orch()
    session, turn = _happy_path_to_confirm(orch)
    assert turn.state is State.BOOK_CONFIRM
    confirm = turn.messages[-1]
    assert "IST" in confirm
    assert "2026" in confirm
    assert "PM IST" in confirm or "AM IST" in confirm
    assert session.selected_slot is not None
    assert session.selected_slot.label_ist in confirm or "IST" in confirm


def test_empty_calendar_waitlist_without_email_config() -> None:
    orch = _orch(MockCalendarService(injected_slots=[]))
    open_turn = orch.create_session()
    session = orch.store.get(open_turn.session_id)
    assert session is not None
    orch.handle("I understand", session)
    orch.handle("Ambrosh Patel", session)
    orch.handle("book new", session)
    orch.handle("topic kyc", session)
    turn = orch.handle("time monday afternoon", session)
    assert turn.state is State.CLOSE
    blob = "\n".join(turn.messages)
    assert "waitlist" in blob.lower()
    assert "IST" in blob
    assert session.pending_booking_code
    record = orch.booking_store.get_by_code(session.pending_booking_code)
    assert record is not None
    assert record.status is BookingStatus.WAITLISTED


def test_empty_calendar_waitlist_with_draft() -> None:
    class _Tools:
        def dispatch(self, name: str, arguments: dict):
            assert name == "gmail_create_draft"
            return "draft-1"

    config = GoogleMcpConfig(
        gemini_api_key="k",
        gemini_model="gemini-3.8-flash",
        calendar_id="primary",
        docs_prebooking_id="doc-1",
        gmail_advisor_to="advisor@example.com",
        secure_link_template="https://example.com/complete?ref={code}",
        oauth_client_secrets=Path("credentials.json"),
        oauth_token_path=Path("token.json"),
        service_account_file=Path(""),
        mcp_server_url="https://example.railway.app/mcp",
        mcp_bearer_token="token",
    )
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))
    orch = Orchestrator(
        session_store=InMemorySessionStore(),
        calendar=MockCalendarService(injected_slots=[]),
        nlu=RuleNluEngine(clock=clock),
        clock=clock,
        waitlist_side_effects=ExecuteWaitlistSideEffects(_Tools(), config),
        google_config=config,
    )
    open_turn = orch.create_session()
    session = orch.store.get(open_turn.session_id)
    assert session is not None
    orch.handle("yes", session)
    orch.handle("Ambrosh Patel", session)
    orch.handle("book new", session)
    orch.handle("topic kyc", session)
    turn = orch.handle("time monday afternoon", session)
    assert turn.state is State.CLOSE
    assert "gmail_create_draft" in session.mcp_tool_trace
    assert any("notification draft" in m.lower() for m in turn.messages)


def test_final_confirm_without_side_effects_stays_recoverable() -> None:
    orch = _orch()  # no booking_side_effects configured
    session, _ = _happy_path_to_confirm(orch)
    turn = orch.handle("confirm", session)
    assert turn.state is State.BOOK_CONFIRM
    assert any("not configured" in m.lower() or "couldn’t complete" in m.lower() for m in turn.messages)


def test_disclaimer_blocks_without_ack() -> None:
    orch = _orch()
    open_turn = orch.create_session()
    session = orch.store.get(open_turn.session_id)
    assert session is not None
    turn = orch.handle("book new", session)
    assert turn.state is State.DISCLAIMER_AWAIT_ACK
    assert any("acknowledge" in m.lower() for m in turn.messages)


def test_disclaimer_accepts_spoken_yes_i_understand() -> None:
    """Browser STT often concatenates quick-reply phrases into one utterance."""
    orch = _orch()
    open_turn = orch.create_session()
    session = orch.store.get(open_turn.session_id)
    assert session is not None
    turn = orch.handle("Yes i understand", session)
    assert turn.state is State.COLLECT_NAME
    turn = orch.handle("Ambrosh Patel", session)
    assert turn.state is State.INTENT_ROUTING


def test_pii_gate_does_not_advance() -> None:
    orch = _orch()
    open_turn = orch.create_session()
    session = orch.store.get(open_turn.session_id)
    assert session is not None
    orch.handle("yes", session)
    orch.handle("Ambrosh Patel", session)
    state_before = session.state
    turn = orch.handle("my email is user@example.com", session)
    assert session.state is state_before
    assert PII_REDIRECT_MESSAGE in turn.messages


def test_phone_pii_blocked() -> None:
    orch = _orch()
    open_turn = orch.create_session()
    session = orch.store.get(open_turn.session_id)
    assert session is not None
    orch.handle("yes", session)
    orch.handle("Ambrosh Patel", session)
    turn = orch.handle("call me at +91 98765 43210", session)
    assert any("secure link" in m.lower() for m in turn.messages)


def test_advice_refusal() -> None:
    orch = _orch()
    open_turn = orch.create_session()
    session = orch.store.get(open_turn.session_id)
    assert session is not None
    orch.handle("yes", session)
    orch.handle("Ambrosh Patel", session)
    turn = orch.handle("which fund should I buy?", session)
    assert any("investment advice" in m.lower() for m in turn.messages)
    assert turn.state is State.INTENT_ROUTING
