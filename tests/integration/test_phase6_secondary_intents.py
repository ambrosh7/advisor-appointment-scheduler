"""Phase 6: reschedule, cancel, what_to_prepare, check_availability via chat."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from api.chat.app import create_app
from domain.calendar import MockCalendarService
from domain.clock import FixedClock
from domain.enums import BookingStatus, Topic
from domain.formatting import build_slot
from domain.models import BookingRecord
from domain.store import InMemoryBookingStore
from integrations.booking_agent.cancel import ExecuteCancelSideEffects
from integrations.booking_agent.reschedule import ExecuteRescheduleSideEffects
from integrations.google_mcp.config import GoogleMcpConfig
from integrations.google_mcp.hybrid_tools import HybridBookingTools
from integrations.google_mcp.tools import GoogleMcpTools
from nlu.engine import RuleNluEngine
from nlu.pii import PII_REDIRECT_MESSAGE
from session.orchestrator import Orchestrator
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


def _seed_booking(store: InMemoryBookingStore, code: str = "NL-A742") -> BookingRecord:
    start = datetime(2026, 4, 6, 7, 30, tzinfo=timezone.utc)  # 13:00 IST
    end = datetime(2026, 4, 6, 8, 0, tzinfo=timezone.utc)
    record = BookingRecord(
        code=code,
        topic=Topic.KYC_ONBOARDING,
        slot=build_slot(start, end),
        created_at_utc=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
        status=BookingStatus.TENTATIVE,
        calendar_event_id="evt-old-1",
    )
    store.save(record)
    return record


def _orch_phase6():
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))
    config = _config()
    clients = make_recording_clients()
    remote = _FakeRemote()
    tools = HybridBookingTools(
        local_calendar=GoogleMcpTools(clients, config),
        remote=remote,  # type: ignore[arg-type]
        config=config,
    )
    booking_store = InMemoryBookingStore()
    calendar = MockCalendarService()
    calendar.mark_busy(datetime(2026, 4, 6, 7, 30, tzinfo=timezone.utc))
    orch = Orchestrator(
        session_store=InMemorySessionStore(),
        calendar=calendar,
        nlu=RuleNluEngine(clock=clock),
        clock=clock,
        booking_store=booking_store,
        cancel_side_effects=ExecuteCancelSideEffects(tools=tools, config=config),
        reschedule_side_effects=ExecuteRescheduleSideEffects(tools=tools, config=config),
        google_config=config,
    )
    return orch, clients, remote, booking_store


def _ack(c: TestClient, sid: str) -> None:
    assert c.post(f"/session/{sid}/message", json={"text": "yes"}).json()["state"] == (
        "COLLECT_NAME"
    )
    assert c.post(f"/session/{sid}/message", json={"text": "Ambrosh Patel"}).json()["state"] == (
        "INTENT_ROUTING"
    )


def test_api_reschedule_subgraph() -> None:
    orch, clients, remote, booking_store = _orch_phase6()
    _seed_booking(booking_store)
    c = TestClient(create_app(orch))
    sid = c.post("/session").json()["session_id"]
    _ack(c, sid)

    def say(text: str) -> dict:
        return c.post(f"/session/{sid}/message", json={"text": text}).json()

    assert say("reschedule")["state"] == "RESCHEDULE_COLLECT_CODE"
    r = say("NL-A742")
    assert r["state"] == "RESCHEDULE_COLLECT_CODE"
    assert any("prefer the new slot" in m.lower() for m in r["messages"])

    r = say("time tuesday morning")
    assert r["state"] == "RESCHEDULE_OFFER_SLOTS"
    assert any("1." in m for m in r["messages"])

    r = say("1")
    assert r["state"] == "RESCHEDULE_OFFER_SLOTS"
    assert any("confirm" in m.lower() for m in r["messages"])
    assert any("IST" in m for m in r["messages"])

    done = say("confirm")
    assert done["state"] == "CLOSE"
    assert any("rescheduled" in m.lower() for m in done["messages"])
    assert any("NL-A742" in m for m in done["messages"])

    record = booking_store.get_by_code("NL-A742")
    assert record is not None
    assert record.status is BookingStatus.TENTATIVE
    assert record.calendar_event_id == "evt-1"
    assert "calendar_delete_hold" in (
        c.get(f"/session/{sid}").json()["mcp_tool_trace"]
    )
    assert "calendar_create_hold" in c.get(f"/session/{sid}").json()["mcp_tool_trace"]
    assert len(clients.calendar.deleted) == 1
    assert len(clients.calendar.events_created) == 1
    assert any(n == "google_docs_append_text" for n, _ in remote.calls)


def test_api_cancel_subgraph() -> None:
    orch, clients, remote, booking_store = _orch_phase6()
    _seed_booking(booking_store)
    c = TestClient(create_app(orch))
    sid = c.post("/session").json()["session_id"]
    _ack(c, sid)

    def say(text: str) -> dict:
        return c.post(f"/session/{sid}/message", json={"text": text}).json()

    r = say("cancel")
    assert r["state"] == "CANCEL_COLLECT_CODE"
    r = say("NL-A742")
    assert r["state"] == "CANCEL_CONFIRM"
    assert any("confirm" in m.lower() for m in r["messages"])

    done = say("confirm")
    assert done["state"] == "CLOSE"
    assert any("cancelled" in m.lower() for m in done["messages"])

    record = booking_store.get_by_code("NL-A742")
    assert record is not None
    assert record.status is BookingStatus.CANCELLED
    debug = c.get(f"/session/{sid}").json()
    assert "calendar_delete_hold" in debug["mcp_tool_trace"]
    assert "docs_append_prebooking" in debug["mcp_tool_trace"]
    assert "gmail_create_draft" in debug["mcp_tool_trace"]
    assert len(clients.calendar.deleted) == 1
    assert any("cancelled" in str(args).lower() for _, args in remote.calls)


def test_api_what_to_prepare_static_snippet() -> None:
    orch, _, _, _ = _orch_phase6()
    c = TestClient(create_app(orch))
    sid = c.post("/session").json()["session_id"]
    _ack(c, sid)

    def say(text: str) -> dict:
        return c.post(f"/session/{sid}/message", json={"text": text}).json()

    r = say("what to prepare")
    assert r["state"] == "PREPARE_TOPIC_OR_GENERIC"
    assert any("pick a topic" in m.lower() or "kyc" in m.lower() for m in r["messages"])

    r = say("topic kyc")
    assert r["state"] == "INTENT_ROUTING"
    blob = "\n".join(r["messages"]).lower()
    assert "kyc" in blob
    assert "aadhaar" in blob or "photo id" in blob
    assert "what would you like to do" in blob


def test_api_check_availability_peek_only() -> None:
    orch, clients, _, booking_store = _orch_phase6()
    c = TestClient(create_app(orch))
    sid = c.post("/session").json()["session_id"]
    _ack(c, sid)

    def say(text: str) -> dict:
        return c.post(f"/session/{sid}/message", json={"text": text}).json()

    r = say("check availability")
    assert r["state"] == "AVAILABILITY_QUERY"
    r = say("time monday afternoon")
    assert r["state"] == "INTENT_ROUTING"
    blob = "\n".join(r["messages"]).lower()
    assert "peek" in blob or "nothing was booked" in blob
    assert "1." in "\n".join(r["messages"])
    assert "book new" in blob
    assert len(booking_store) == 0
    assert len(clients.calendar.events_created) == 0


def test_secondary_intents_never_prompt_for_pii() -> None:
    orch, _, _, booking_store = _orch_phase6()
    _seed_booking(booking_store)
    c = TestClient(create_app(orch))
    sid = c.post("/session").json()["session_id"]
    _ack(c, sid)

    def say(text: str) -> dict:
        return c.post(f"/session/{sid}/message", json={"text": text}).json()

    forbidden = ("phone", "email", "account number", "mobile")
    for intent_text in ("reschedule", "cancel", "what to prepare", "check availability"):
        r = say(intent_text)
        joined = "\n".join(r["messages"]).lower()
        for word in forbidden:
            assert word not in joined or "never phone or email" in joined
        # Reset to routing for next intent where needed
        if r["state"] != "INTENT_ROUTING":
            # abandon mid-flow by starting a fresh session path via book-ish reset
            sid = c.post("/session").json()["session_id"]
            _ack(c, sid)

    # PII still blocked mid cancel
    sid = c.post("/session").json()["session_id"]
    _ack(c, sid)
    say("cancel")
    blocked = say("my email is user@example.com")
    assert PII_REDIRECT_MESSAGE in blocked["messages"]
    assert blocked["state"] == "CANCEL_COLLECT_CODE"
