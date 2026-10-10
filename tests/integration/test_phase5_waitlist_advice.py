"""Phase 5: empty calendar → waitlist; advice interruption mid-flow; IST confirm."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from api.chat.app import create_app
from domain.calendar import MockCalendarService
from domain.clock import FixedClock
from domain.enums import BookingStatus
from integrations.booking_agent.execute import ExecuteBookingSideEffects
from integrations.booking_agent.gemini_agent import (
    GeminiBookingAgent,
    scripted_gemini_success_sequence,
)
from integrations.booking_agent.waitlist import ExecuteWaitlistSideEffects
from integrations.google_mcp.config import GoogleMcpConfig
from integrations.google_mcp.hybrid_tools import HybridBookingTools
from integrations.google_mcp.tools import GoogleMcpTools
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
        advice_educational_url="https://example.com/learn/basics",
    )


class _FakeRemote:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": f"ok:{name}"}]}


def _tools(config: GoogleMcpConfig):
    clients = make_recording_clients()
    remote = _FakeRemote()
    tools = HybridBookingTools(
        local_calendar=GoogleMcpTools(clients, config),
        remote=remote,  # type: ignore[arg-type]
        config=config,
    )
    return tools, clients, remote


def _orch_waitlist_empty_calendar():
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))
    config = _config()
    tools, clients, remote = _tools(config)
    orch = Orchestrator(
        session_store=InMemorySessionStore(),
        calendar=MockCalendarService(injected_slots=[]),
        nlu=RuleNluEngine(clock=clock),
        clock=clock,
        waitlist_side_effects=ExecuteWaitlistSideEffects(tools=tools, config=config),
        google_config=config,
    )
    return orch, clients, remote


def _orch_booking_with_advice_path():
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))
    config = _config()
    tools, clients, remote = _tools(config)

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
        waitlist_side_effects=ExecuteWaitlistSideEffects(tools=tools, config=config),
        google_config=config,
    )
    return orch, clients, remote


def test_empty_calendar_goes_to_waitlist_and_drafts_email() -> None:
    orch, _clients, remote = _orch_waitlist_empty_calendar()
    c = TestClient(create_app(orch))
    sid = c.post("/session").json()["session_id"]

    def say(text: str) -> dict:
        return c.post(f"/session/{sid}/message", json={"text": text}).json()

    assert say("yes")["state"] == "COLLECT_NAME"
    assert say("Ambrosh Patel")["state"] == "INTENT_ROUTING"
    assert say("book new")["state"] == "BOOK_TOPIC"
    assert say("topic kyc")["state"] == "BOOK_TIME_PREFERENCE"
    done = say("time monday afternoon")
    assert done["state"] == "CLOSE"
    blob = "\n".join(done["messages"])
    assert "waitlist" in blob.lower()
    assert "Booking code:" in blob
    assert "IST" in blob
    assert "KYC Onboarding" in blob
    assert any("example.com/complete?ref=" in m for m in done["messages"])

    session = orch.store.get(sid)
    assert session is not None
    assert session.state is State.CLOSE
    assert "gmail_create_draft" in session.mcp_tool_trace
    code = session.pending_booking_code
    assert code
    record = orch.booking_store.get_by_code(code)
    assert record is not None
    assert record.status is BookingStatus.WAITLISTED
    assert [n for n, _ in remote.calls] == ["gmail_send_email"]
    assert "waitlist" in remote.calls[0][1]["subject"].lower()


def test_advice_interruption_mid_flow_then_confirm() -> None:
    orch, clients, remote = _orch_booking_with_advice_path()
    c = TestClient(create_app(orch))
    sid = c.post("/session").json()["session_id"]

    def say(text: str) -> dict:
        return c.post(f"/session/{sid}/message", json={"text": text}).json()

    assert say("yes")["state"] == "COLLECT_NAME"
    assert say("Ambrosh Patel")["state"] == "INTENT_ROUTING"
    assert say("book new")["state"] == "BOOK_TOPIC"
    assert say("topic kyc")["state"] == "BOOK_TIME_PREFERENCE"
    offer = say("time monday afternoon")
    assert offer["state"] == "BOOK_OFFER_SLOTS"
    confirm = say("1")
    assert confirm["state"] == "BOOK_CONFIRM"
    confirm_text = confirm["messages"][-1]
    assert "IST" in confirm_text
    assert "KYC Onboarding" in confirm_text
    # Full date/time style: weekday + day + month + year + time + IST
    assert "2026" in confirm_text
    assert "PM IST" in confirm_text or "AM IST" in confirm_text

    advice = say("should I buy stocks?")
    assert advice["state"] == "BOOK_CONFIRM"
    advice_blob = "\n".join(advice["messages"])
    assert "investment advice" in advice_blob.lower()
    assert "https://example.com/learn/basics" in advice_blob

    done = say("confirm")
    assert done["state"] == "CLOSE"
    assert any("Booking code:" in m for m in done["messages"])
    assert len(clients.calendar.events_created) == 1
    assert "gmail_send_email" in [n for n, _ in remote.calls]
