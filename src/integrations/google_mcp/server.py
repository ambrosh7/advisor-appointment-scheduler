"""
FastMCP server: real Google Calendar / Docs / Gmail tools.

Run standalone:
  PYTHONPATH=src python -m integrations.google_mcp.server
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from integrations.google_mcp.clients import GoogleWorkspaceClients
from integrations.google_mcp.config import GoogleMcpConfig
from integrations.google_mcp.tools import GoogleMcpTools

logger = logging.getLogger(__name__)

_tools: Optional[GoogleMcpTools] = None


def get_tools() -> GoogleMcpTools:
    global _tools
    if _tools is None:
        config = GoogleMcpConfig.from_env()
        clients = GoogleWorkspaceClients.from_config(config)
        _tools = GoogleMcpTools(clients, config)
    return _tools


def set_tools(tools: GoogleMcpTools) -> None:
    """Inject tools instance (tests / app wiring)."""
    global _tools
    _tools = tools


try:
    from fastmcp import FastMCP

    mcp = FastMCP("advisor-booking")

    def create_mcp_server(tools: Optional[GoogleMcpTools] = None) -> Any:
        if tools is not None:
            set_tools(tools)
        return mcp

    @mcp.tool()
    def calendar_create_hold(
        title: str,
        start_utc: str,
        end_utc: str,
        calendar_id: str,
        idempotency_key: str,
    ) -> str:
        """Create a tentative calendar hold via Google Calendar API. Returns external_event_id."""
        return get_tools().calendar_create_hold(
            title=title,
            start_utc=start_utc,
            end_utc=end_utc,
            calendar_id=calendar_id,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def calendar_delete_hold(event_id: str, calendar_id: str) -> None:
        """Delete an existing tentative hold via Google Calendar API."""
        get_tools().calendar_delete_hold(event_id=event_id, calendar_id=calendar_id)

    @mcp.tool()
    def docs_append_prebooking(doc_id: str, line: str, idempotency_key: str) -> None:
        """Append a pre-booking line to the Advisor Pre-Bookings Google Doc. No PII."""
        get_tools().docs_append_prebooking(
            doc_id=doc_id, line=line, idempotency_key=idempotency_key
        )

    @mcp.tool()
    def gmail_create_draft(to: str, subject: str, body_markdown: str) -> str:
        """Create a real Gmail draft. Never auto-sends; returns draft_id."""
        return get_tools().gmail_create_draft(
            to=to, subject=subject, body_markdown=body_markdown
        )

except ImportError:
    logger.warning("fastmcp not installed — using in-process MCP tool registry shim")

    class _ShimMcp:
        """Minimal registry compatible with our tool surface when FastMCP is absent."""

        def __init__(self, name: str) -> None:
            self.name = name
            self.tools: dict[str, Callable[..., Any]] = {}

        def tool(self) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
                self.tools[fn.__name__] = fn
                return fn

            return decorator

        def run(self) -> None:
            raise RuntimeError(
                "Install fastmcp to run the MCP server: pip install 'fastmcp>=2.0'"
            )

    mcp = _ShimMcp("advisor-booking")

    def create_mcp_server(tools: Optional[GoogleMcpTools] = None) -> Any:
        if tools is not None:
            set_tools(tools)
        return mcp

    @mcp.tool()
    def calendar_create_hold(
        title: str,
        start_utc: str,
        end_utc: str,
        calendar_id: str,
        idempotency_key: str,
    ) -> str:
        """Create a tentative calendar hold via Google Calendar API. Returns external_event_id."""
        return get_tools().calendar_create_hold(
            title=title,
            start_utc=start_utc,
            end_utc=end_utc,
            calendar_id=calendar_id,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def calendar_delete_hold(event_id: str, calendar_id: str) -> None:
        """Delete an existing tentative hold via Google Calendar API."""
        get_tools().calendar_delete_hold(event_id=event_id, calendar_id=calendar_id)

    @mcp.tool()
    def docs_append_prebooking(doc_id: str, line: str, idempotency_key: str) -> None:
        """Append a pre-booking line to the Advisor Pre-Bookings Google Doc. No PII."""
        get_tools().docs_append_prebooking(
            doc_id=doc_id, line=line, idempotency_key=idempotency_key
        )

    @mcp.tool()
    def gmail_create_draft(to: str, subject: str, body_markdown: str) -> str:
        """Create a real Gmail draft. Never auto-sends; returns draft_id."""
        return get_tools().gmail_create_draft(
            to=to, subject=subject, body_markdown=body_markdown
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run()
