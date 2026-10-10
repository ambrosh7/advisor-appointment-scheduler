"""
Hybrid tool dispatcher for Phase 4:

- Calendar hold/delete → local Google Calendar API (``GoogleMcpTools``)
- Docs append → Railway MCP ``google_docs_append_text``
- Gmail notify → Railway MCP ``gmail_send_email`` (sends; not a draft)

If Railway has no Google OAuth tokens (``MISSING_OAUTH_CONFIG``), Docs/Gmail
fall back to the local Google APIs using this project's credentials.

Gemini still calls the Phase-4 logical names; this layer maps them.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from integrations.google_mcp.config import GoogleMcpConfig
from integrations.google_mcp.remote_client import (
    RemoteMcpClient,
    RemoteMcpError,
    _content_text,
)
from integrations.google_mcp.tools import GoogleMcpTools

logger = logging.getLogger(__name__)


def _remote_oauth_missing(exc: BaseException) -> bool:
    text = str(exc)
    return "MISSING_OAUTH_CONFIG" in text or "No Google OAuth tokens found" in text


class HybridBookingTools:
    def __init__(
        self,
        local_calendar: GoogleMcpTools,
        remote: RemoteMcpClient,
        config: Optional[GoogleMcpConfig] = None,
    ) -> None:
        self._local = local_calendar
        self._remote = remote
        self._config = config or GoogleMcpConfig.from_env()

    def calendar_delete_hold(self, event_id: str, calendar_id: str) -> None:
        self._local.calendar_delete_hold(event_id=event_id, calendar_id=calendar_id)

    def dispatch(self, name: str, arguments: dict) -> Any:
        if name in {"calendar_create_hold", "calendar_delete_hold"}:
            return self._local.dispatch(name, arguments)

        if name == "docs_append_prebooking":
            return self._docs_append(arguments)

        if name == "gmail_create_draft":
            return self._gmail_notify(arguments)

        raise ValueError(f"Unknown MCP tool: {name}")

    def _docs_append(self, arguments: dict) -> Any:
        doc_id = arguments.get("doc_id") or self._config.docs_prebooking_id
        line = arguments["line"]
        idem = arguments.get("idempotency_key") or ""
        text = f"{line}" if not idem else f"{line} [{idem}]"
        docs_args: dict = {
            "document_id": doc_id,
            "text": text,
            "prepend_newline": True,
        }
        if idem:
            docs_args["request_id"] = idem
        try:
            result = self._remote.call_tool("google_docs_append_text", docs_args)
            logger.info("remote docs append ok doc_id=%s", doc_id)
            return _content_text(result) or {"ok": True}
        except RemoteMcpError as exc:
            if not _remote_oauth_missing(exc):
                raise
            logger.warning(
                "Railway Docs OAuth missing; falling back to local Docs API"
            )
            return self._local.dispatch("docs_append_prebooking", arguments)

    def _gmail_notify(self, arguments: dict) -> Any:
        # Railway tool sends mail (no draft API on that server).
        to_addr = arguments.get("to") or self._config.gmail_advisor_to
        subject = arguments["subject"]
        body = arguments.get("body_markdown") or arguments.get("body") or ""
        request_id = arguments.get("idempotency_key") or arguments.get("request_id")
        mail_args: dict = {
            "to": to_addr,
            "subject": subject,
            "body": body,
            "body_format": "text",
        }
        if request_id:
            mail_args["request_id"] = request_id
        try:
            result = self._remote.call_tool("gmail_send_email", mail_args)
            text = _content_text(result)
            logger.info("remote gmail_send_email ok to=%s", to_addr)
            return text or {"ok": True, "mode": "sent"}
        except RemoteMcpError as exc:
            if not _remote_oauth_missing(exc):
                raise
            logger.warning(
                "Railway Gmail OAuth missing; falling back to local Gmail draft"
            )
            return self._local.dispatch("gmail_create_draft", arguments)
