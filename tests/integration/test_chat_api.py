"""Chat HTTP API — Phase 2 happy path to ready-to-confirm."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from api.chat.app import create_app
from domain.calendar import MockCalendarService
from domain.clock import FixedClock
from nlu.engine import RuleNluEngine
from session.orchestrator import Orchestrator
from session.store import InMemorySessionStore


def _client() -> TestClient:
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))
    orch = Orchestrator(
        session_store=InMemorySessionStore(),
        calendar=MockCalendarService(),
        nlu=RuleNluEngine(clock=clock),
        clock=clock,
    )
    return TestClient(create_app(orch))


def test_health() -> None:
    c = _client()
    assert c.get("/health").json()["status"] == "ok"


def test_api_happy_path_to_confirm() -> None:
    c = _client()
    r = c.post("/session")
    assert r.status_code == 200
    body = r.json()
    sid = body["session_id"]
    assert body["state"] == "DISCLAIMER_AWAIT_ACK"

    def say(text: str) -> dict:
        resp = c.post(f"/session/{sid}/message", json={"text": text})
        assert resp.status_code == 200
        return resp.json()

    assert say("yes")["state"] == "COLLECT_NAME"
    assert say("Ambrosh Patel")["state"] == "INTENT_ROUTING"
    assert say("book new")["state"] == "BOOK_TOPIC"
    assert say("topic kyc")["state"] == "BOOK_TIME_PREFERENCE"
    offer = say("time monday afternoon")
    assert offer["state"] == "BOOK_OFFER_SLOTS"
    assert any("1." in m for m in offer["messages"])

    confirm = say("1")
    assert confirm["state"] == "BOOK_CONFIRM"
    assert any("IST" in m for m in confirm["messages"])

    debug = c.get(f"/session/{sid}").json()
    assert debug["state"] == "BOOK_CONFIRM"
    assert debug["selected_slot"] is not None


def test_unknown_session_404() -> None:
    c = _client()
    r = c.post("/session/does-not-exist/message", json={"text": "hi"})
    assert r.status_code == 404
