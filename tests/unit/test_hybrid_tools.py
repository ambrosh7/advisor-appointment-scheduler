"""Hybrid dispatcher: local calendar + remote Railway Docs/Gmail."""

from __future__ import annotations

from pathlib import Path

from integrations.google_mcp.config import GoogleMcpConfig
from integrations.google_mcp.hybrid_tools import HybridBookingTools
from integrations.google_mcp.tools import GoogleMcpTools
from tests.support.recording_google import make_recording_clients


class FakeRemote:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": f"ok:{name}"}]}


def _config() -> GoogleMcpConfig:
    return GoogleMcpConfig(
        gemini_api_key="k",
        gemini_model="gemini-2.0-flash",
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


def test_hybrid_maps_docs_and_gmail_to_railway_tools() -> None:
    config = _config()
    local = GoogleMcpTools(make_recording_clients(), config)
    remote = FakeRemote()
    tools = HybridBookingTools(local, remote, config)  # type: ignore[arg-type]

    tools.dispatch(
        "docs_append_prebooking",
        {"doc_id": "doc-1", "line": "hello", "idempotency_key": "NL-A742"},
    )
    tools.dispatch(
        "gmail_create_draft",
        {
            "to": "advisor@example.com",
            "subject": "sub",
            "body_markdown": "body",
        },
    )

    assert remote.calls[0][0] == "google_docs_append_text"
    assert remote.calls[0][1]["document_id"] == "doc-1"
    assert "hello" in remote.calls[0][1]["text"]
    assert remote.calls[1][0] == "gmail_send_email"
    assert remote.calls[1][1]["body"] == "body"


class FakeRemoteMissingOAuth:
    def call_tool(self, name: str, arguments: dict):
        from integrations.google_mcp.remote_client import RemoteMcpError

        raise RemoteMcpError(
            'MCP tool failed: {"success": false, "error": '
            '{"code": "MISSING_OAUTH_CONFIG", '
            '"message": "No Google OAuth tokens found."}}'
        )


def test_hybrid_docs_gmail_fallback_when_railway_oauth_missing() -> None:
    config = _config()
    clients = make_recording_clients()
    local = GoogleMcpTools(clients, config)
    tools = HybridBookingTools(local, FakeRemoteMissingOAuth(), config)  # type: ignore[arg-type]

    tools.dispatch(
        "docs_append_prebooking",
        {"doc_id": "doc-1", "line": "hello", "idempotency_key": "NL-A742"},
    )
    draft_id = tools.dispatch(
        "gmail_create_draft",
        {
            "to": "advisor@example.com",
            "subject": "sub",
            "body_markdown": "body",
        },
    )

    assert clients.docs.appended  # type: ignore[attr-defined]
    assert draft_id == "draft-1"
    assert clients.gmail.created_drafts  # type: ignore[attr-defined]


def test_hybrid_calendar_stays_local() -> None:
    config = _config()
    clients = make_recording_clients()
    local = GoogleMcpTools(clients, config)
    remote = FakeRemote()
    tools = HybridBookingTools(local, remote, config)  # type: ignore[arg-type]

    event_id = tools.dispatch(
        "calendar_create_hold",
        {
            "title": "Advisor Q&A — KYC Onboarding — NL-A742",
            "start_utc": "2026-04-13T06:30:00+00:00",
            "end_utc": "2026-04-13T07:00:00+00:00",
            "calendar_id": "primary",
            "idempotency_key": "booking:NL-A742",
        },
    )
    assert event_id == "evt-1"
    assert remote.calls == []
    assert len(clients.calendar.events_created) == 1
