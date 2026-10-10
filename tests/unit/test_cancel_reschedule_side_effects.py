"""Phase 6 cancel / reschedule MCP side effects."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from domain.enums import Topic
from domain.formatting import build_slot
from integrations.booking_agent.cancel import (
    CancelExecutionRequest,
    ExecuteCancelSideEffects,
)
from integrations.booking_agent.reschedule import (
    ExecuteRescheduleSideEffects,
    RescheduleExecutionRequest,
)
from integrations.google_mcp.config import GoogleMcpConfig


def _config() -> GoogleMcpConfig:
    return GoogleMcpConfig(
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


def _slot(hour: int = 9):
    start = datetime(2026, 4, 7, hour, 0, tzinfo=timezone.utc)
    end = datetime(2026, 4, 7, hour, 30, tzinfo=timezone.utc)
    return build_slot(start, end)


def test_cancel_calls_delete_docs_gmail() -> None:
    calls: list[tuple[str, dict]] = []

    class _Tools:
        def dispatch(self, name: str, arguments: dict):
            calls.append((name, arguments))
            return "draft-1" if name == "gmail_create_draft" else {"ok": True}

    result = ExecuteCancelSideEffects(_Tools(), _config()).execute(
        CancelExecutionRequest(
            topic=Topic.KYC_ONBOARDING,
            slot=_slot(),
            booking_code="NL-A742",
            calendar_event_id="evt-old",
        )
    )
    assert result.ok
    assert result.tool_trace == [
        "calendar_delete_hold",
        "docs_append_prebooking",
        "gmail_create_draft",
    ]
    assert any("cancelled" in c[1].get("line", "").lower() for c in calls)


def test_reschedule_delete_then_create() -> None:
    calls: list[str] = []

    class _Tools:
        def dispatch(self, name: str, arguments: dict):
            calls.append(name)
            if name == "calendar_create_hold":
                return "evt-new"
            return {"ok": True}

    old = _slot(9)
    new = _slot(11)
    result = ExecuteRescheduleSideEffects(_Tools(), _config()).execute(
        RescheduleExecutionRequest(
            topic=Topic.SIP_MANDATES,
            old_slot=old,
            new_slot=new,
            booking_code="AB-C123",
            old_calendar_event_id="evt-old",
        )
    )
    assert result.ok
    assert result.calendar_event_id == "evt-new"
    assert calls == [
        "calendar_delete_hold",
        "calendar_create_hold",
        "docs_append_prebooking",
    ]
