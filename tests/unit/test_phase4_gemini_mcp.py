"""Phase 4: Gemini agent tool-calls actual Google MCP tools."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from domain.enums import Topic
from domain.formatting import build_slot
from integrations.booking_agent.execute import (
    BookingExecutionRequest,
    ExecuteBookingSideEffects,
)
from integrations.booking_agent.gemini_agent import (
    GeminiBookingAgent,
    scripted_gemini_success_sequence,
)
from integrations.google_mcp.config import GoogleMcpConfig
from integrations.google_mcp.tools import GoogleMcpTools
from tests.support.recording_google import make_recording_clients


def _config() -> GoogleMcpConfig:
    return GoogleMcpConfig(
        gemini_api_key="test-key",
        gemini_model="gemini-2.0-flash",
        calendar_id="primary",
        docs_prebooking_id="doc-prebook-1",
        gmail_advisor_to="advisor@example.com",
        secure_link_template="https://example.com/complete?ref={code}",
        oauth_client_secrets=__import__("pathlib").Path("credentials.json"),
        oauth_token_path=__import__("pathlib").Path("token.json"),
        service_account_file=__import__("pathlib").Path(""),
        mcp_server_url="https://example.railway.app/mcp",
        mcp_bearer_token="test-token",
    )


def _request() -> BookingExecutionRequest:
    start = datetime(2026, 4, 13, 6, 30, tzinfo=timezone.utc)
    slot = build_slot(start, start + timedelta(minutes=30))
    return BookingExecutionRequest(
        topic=Topic.KYC_ONBOARDING,
        slot=slot,
        booking_code="NL-A742",
        correlation_id="corr-1",
        calendar_id="primary",
        doc_id="doc-prebook-1",
        advisor_email="advisor@example.com",
    )


def test_gemini_agent_invokes_three_mcp_tools() -> None:
    config = _config()
    clients = make_recording_clients()
    tools = GoogleMcpTools(clients, config)
    req = _request()
    agent = GeminiBookingAgent(
        tools=tools,
        config=config,
        generate_content=scripted_gemini_success_sequence(req, config),
    )
    result = ExecuteBookingSideEffects(agent)(req)

    assert result.ok is True
    assert result.tool_trace == [
        "calendar_create_hold",
        "docs_append_prebooking",
        "gmail_create_draft",
    ]
    assert result.calendar_event_id == "evt-1"
    assert result.gmail_draft_id == "draft-1"
    assert result.secure_url == "https://example.com/complete?ref=NL-A742"
    assert len(clients.calendar.events_created) == 1
    title = clients.calendar.events_created[0]["body"]["summary"]
    assert title == "Advisor Q&A — KYC Onboarding — NL-A742"
    assert len(clients.docs.appended) == 1
    assert len(clients.gmail.created_drafts) == 1


def test_docs_failure_compensates_calendar_delete() -> None:
    config = _config()
    clients = make_recording_clients()
    clients.docs.fail_remaining = 5  # survive with_retry
    tools = GoogleMcpTools(clients, config)
    req = _request()

    # Script: calendar ok, then docs fails via API
    planned = scripted_gemini_success_sequence(req, config)

    agent = GeminiBookingAgent(
        tools=tools,
        config=config,
        generate_content=planned,
    )
    result = agent.execute(req)
    assert result.ok is False
    assert "docs_append_prebooking" in result.tool_trace
    assert "calendar_delete_hold" in result.tool_trace
    assert clients.calendar.deleted == ["evt-1"]


def test_mcp_tools_dispatch_unknown() -> None:
    tools = GoogleMcpTools(make_recording_clients(), _config())
    with pytest.raises(ValueError, match="Unknown MCP tool"):
        tools.dispatch("not_a_tool", {})
