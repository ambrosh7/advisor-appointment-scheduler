"""Unit tests for ExecuteWaitlistSideEffects."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from domain.enums import Topic
from domain.models import TimeSlot
from integrations.booking_agent.waitlist import (
    ExecuteWaitlistSideEffects,
    WaitlistExecutionRequest,
    waitlist_email_body,
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


def _slot() -> TimeSlot:
    start = datetime(2026, 4, 13, 3, 30, tzinfo=timezone.utc)
    end = datetime(2026, 4, 13, 4, 0, tzinfo=timezone.utc)
    return TimeSlot(
        start_utc=start,
        end_utc=end,
        label_ist="Monday, 13 April 2026, 9:00 AM IST",
    )


class _FakeTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def dispatch(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        return "draft-99"


def test_waitlist_email_body_marks_waitlist() -> None:
    body = waitlist_email_body(
        code="AB-C123",
        topic=Topic.KYC_ONBOARDING,
        slot=_slot(),
        secure_url="https://example.com/complete?ref=AB-C123",
    )
    assert "Waitlist" in body
    assert "AB-C123" in body
    assert "9:00 AM IST" in body


def test_execute_waitlist_dispatches_gmail_create_draft() -> None:
    tools = _FakeTools()
    fx = ExecuteWaitlistSideEffects(tools=tools, config=_config())
    result = fx.execute(
        WaitlistExecutionRequest(
            topic=Topic.KYC_ONBOARDING,
            slot=_slot(),
            booking_code="AB-C123",
        )
    )
    assert result.ok
    assert result.gmail_draft_id == "draft-99"
    assert result.tool_trace == ["gmail_create_draft"]
    assert tools.calls[0][0] == "gmail_create_draft"
    args = tools.calls[0][1]
    assert args["to"] == "advisor@example.com"
    assert "waitlist" in args["subject"].lower()
    assert "AB-C123" in args["subject"]
    assert "Waitlist" in args["body_markdown"]
