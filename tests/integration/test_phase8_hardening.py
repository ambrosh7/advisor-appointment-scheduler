"""Phase 8: rate limits, degraded MCP mode, failure injection via chat API."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.chat.app import create_app
from domain.calendar import MockCalendarService
from domain.clock import FixedClock
from integrations.booking_agent.execute import ExecuteBookingSideEffects
from integrations.google_mcp.config import GoogleMcpConfig
from integrations.google_mcp.hybrid_tools import HybridBookingTools
from integrations.google_mcp.tools import GoogleMcpTools
from nlu.engine import RuleNluEngine
from ops.config import OpsConfig
from ops.degraded import GmailOnlyDegradedQueue, ResilientBookingSideEffects
from session.copy import MCP_DEGRADED_RETRY
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
    )


class _FailCalendarRemote:
    """Docs/Gmail remote OK; used with local calendar that raises."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": f"ok:{name}"}]}


class _TimeoutCalendarTools:
    """Inject Calendar timeout; Docs/Gmail via hybrid remote still work."""

    def __init__(self, inner: GoogleMcpTools) -> None:
        self._inner = inner

    def calendar_delete_hold(self, event_id: str, calendar_id: str) -> None:
        self._inner.calendar_delete_hold(event_id=event_id, calendar_id=calendar_id)

    def dispatch(self, name: str, arguments: dict):
        if name == "calendar_create_hold":
            raise TimeoutError("simulated Google Calendar timeout")
        return self._inner.dispatch(name, arguments)


def _orch_with_failing_calendar():
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))
    config = _config()
    clients = make_recording_clients()
    remote = _FailCalendarRemote()
    local = GoogleMcpTools(clients, config)
    # Hybrid still routes calendar to local — wrap local to timeout
    flaky_local = _TimeoutCalendarTools(local)
    tools = HybridBookingTools(
        local_calendar=flaky_local,  # type: ignore[arg-type]
        remote=remote,  # type: ignore[arg-type]
        config=config,
    )

    class _Agent:
        def execute(self, request):
            # Bypass Gemini — call tools in order like a successful agent would
            from integrations.booking_agent.execute import BookingExecutionResult

            trace: list[str] = []
            try:
                tools.dispatch(
                    "calendar_create_hold",
                    {
                        "title": "t",
                        "start_utc": request.slot.start_utc.isoformat(),
                        "end_utc": request.slot.end_utc.isoformat(),
                        "calendar_id": "primary",
                        "idempotency_key": request.booking_code,
                    },
                )
                trace.append("calendar_create_hold")
            except Exception as exc:  # noqa: BLE001
                return BookingExecutionResult(
                    ok=False,
                    booking_code=request.booking_code,
                    secure_url=config.secure_link_for(request.booking_code),
                    tool_trace=trace,
                    error=f"MCP tool calendar_create_hold failed: {exc}",
                )
            return BookingExecutionResult(
                ok=True,
                booking_code=request.booking_code,
                secure_url=config.secure_link_for(request.booking_code),
                tool_trace=trace,
            )

    primary = ExecuteBookingSideEffects(_Agent())
    degraded = GmailOnlyDegradedQueue(tools=tools, config=config)
    booking = ResilientBookingSideEffects(primary, degraded)
    orch = Orchestrator(
        session_store=InMemorySessionStore(),
        calendar=MockCalendarService(),
        nlu=RuleNluEngine(clock=clock),
        clock=clock,
        booking_side_effects=booking,
        google_config=config,
    )
    return orch, remote


def test_session_create_rate_limited() -> None:
    ops = OpsConfig(
        app_env="test",
        session_create_rate_limit=2,
        session_create_rate_window_s=60.0,
        enable_ttl_job=False,
        redact_user_text=False,
    )
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))
    orch = Orchestrator(
        session_store=InMemorySessionStore(),
        calendar=MockCalendarService(),
        nlu=RuleNluEngine(clock=clock),
        clock=clock,
    )
    with TestClient(
        create_app(orch, ops_config=ops, enable_ttl_job=False)
    ) as c:
        assert c.post("/session").status_code == 200
        assert c.post("/session").status_code == 200
        blocked = c.post("/session")
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers


def test_mcp_timeout_degraded_queues_gmail_via_chat() -> None:
    orch, remote = _orch_with_failing_calendar()
    ops = OpsConfig(enable_ttl_job=False, redact_user_text=False)
    with TestClient(
        create_app(orch, ops_config=ops, enable_ttl_job=False)
    ) as c:
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
        assert done["state"] == "BOOK_CONFIRM"
        blob = "\n".join(done["messages"])
        assert MCP_DEGRADED_RETRY in blob or "queued an advisor email" in blob.lower()
        debug = c.get(f"/session/{sid}").json()
        assert "degraded_gmail_queue" in debug["mcp_tool_trace"]
        assert "gmail_create_draft" in debug["mcp_tool_trace"]
        assert any(n == "gmail_send_email" for n, _ in remote.calls)


def test_health_exposes_phase8_flags() -> None:
    ops = OpsConfig(enable_ttl_job=False)
    orch = Orchestrator(session_store=InMemorySessionStore())
    with TestClient(
        create_app(orch, ops_config=ops, enable_ttl_job=False)
    ) as c:
        h = c.get("/health").json()
        assert h["status"] == "ok"
        assert "phase8_redact_user_text" in h
        assert "phase8_ttl_job" in h


@pytest.mark.live_mcp
def test_live_mcp_placeholder_skipped_without_creds() -> None:
    """Marker for live Google MCP gate — skip when credentials incomplete."""
    config = GoogleMcpConfig.from_env()
    errors = config.validate_for_live()
    if errors:
        pytest.skip("live MCP credentials missing: " + "; ".join(errors))
    # Presence of credentials is enough for the gate hook; deep live E2E is manual.
    assert config.gemini_api_key
