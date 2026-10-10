"""
Google MCP tool implementations backed by live google-api-python-client.

These are the actual MCP tool bodies — not FakeMCP. Google service objects may
be injected for automated tests (API seam), while the tool surface stays real.
"""

from __future__ import annotations

import base64
import logging
from email.message import EmailMessage
from typing import Any, Optional

from integrations.google_mcp.clients import GoogleWorkspaceClients, with_retry
from integrations.google_mcp.config import GoogleMcpConfig

logger = logging.getLogger(__name__)

# Idempotency: event extended property key
_IDEM_PROP = "bookingIdempotencyKey"


class GoogleMcpTools:
    """Callable tool set used by FastMCP and by the Gemini booking agent."""

    def __init__(
        self,
        clients: GoogleWorkspaceClients,
        config: Optional[GoogleMcpConfig] = None,
    ) -> None:
        self._clients = clients
        self._config = config or GoogleMcpConfig.from_env()

    @property
    def correlation_id(self) -> str:
        return self._clients.correlation_id

    def calendar_create_hold(
        self,
        title: str,
        start_utc: str,
        end_utc: str,
        calendar_id: str,
        idempotency_key: str,
    ) -> str:
        """Create a tentative calendar hold. Returns external_event_id."""
        cal_id = calendar_id or self._config.calendar_id
        existing = self._find_by_idempotency(cal_id, idempotency_key)
        if existing:
            logger.info(
                "calendar_create_hold idempotent hit key=%s event=%s",
                idempotency_key,
                existing,
            )
            return existing

        body = {
            "summary": title,
            "description": f"Tentative advisor hold. Idempotency: {idempotency_key}",
            "start": {"dateTime": start_utc, "timeZone": "UTC"},
            "end": {"dateTime": end_utc, "timeZone": "UTC"},
            "status": "tentative",
            "extendedProperties": {
                "private": {_IDEM_PROP: idempotency_key},
            },
        }

        def _call() -> Any:
            return (
                self._clients.calendar.events()
                .insert(calendarId=cal_id, body=body)
                .execute()
            )

        event = with_retry(
            "calendar_create_hold",
            _call,
            correlation_id=self.correlation_id,
            timeout_note="budget_5_10s",
        )
        event_id = event.get("id") or ""
        if not event_id:
            raise RuntimeError("Calendar API returned no event id")
        return event_id

    def calendar_delete_hold(self, event_id: str, calendar_id: str) -> None:
        """Delete an existing tentative hold."""
        cal_id = calendar_id or self._config.calendar_id

        def _call() -> Any:
            return (
                self._clients.calendar.events()
                .delete(calendarId=cal_id, eventId=event_id)
                .execute()
            )

        with_retry(
            "calendar_delete_hold",
            _call,
            correlation_id=self.correlation_id,
        )

    def docs_append_prebooking(
        self,
        doc_id: str,
        line: str,
        idempotency_key: str,
    ) -> None:
        """Append a pre-booking line to Advisor Pre-Bookings. No PII."""
        target = doc_id or self._config.docs_prebooking_id
        if not target:
            raise ValueError("doc_id / GOOGLE_DOCS_PREBOOKING_ID required")

        # Prefix idempotency key so retries are visible / dedupeable manually
        text = f"{line} [{idempotency_key}]\n"

        def _call() -> Any:
            # End-of-document insert
            doc = self._clients.docs.documents().get(documentId=target).execute()
            end_index = doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 1)
            # Insert before final newline
            insert_at = max(1, end_index - 1)
            requests = [
                {
                    "insertText": {
                        "location": {"index": insert_at},
                        "text": text,
                    }
                }
            ]
            return (
                self._clients.docs.documents()
                .batchUpdate(documentId=target, body={"requests": requests})
                .execute()
            )

        with_retry(
            "docs_append_prebooking",
            _call,
            correlation_id=self.correlation_id,
            timeout_note="budget_5s",
        )

    def gmail_create_draft(
        self,
        to: str,
        subject: str,
        body_markdown: str,
    ) -> str:
        """Create a Gmail draft. Never auto-sends; returns draft_id."""
        recipient = to or self._config.gmail_advisor_to
        if not recipient:
            raise ValueError("to / GOOGLE_GMAIL_ADVISOR_TO required")

        message = EmailMessage()
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body_markdown)

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        def _call() -> Any:
            return (
                self._clients.gmail.users()
                .drafts()
                .create(userId="me", body={"message": {"raw": raw}})
                .execute()
            )

        draft = with_retry(
            "gmail_create_draft",
            _call,
            correlation_id=self.correlation_id,
            timeout_note="budget_5s",
        )
        draft_id = draft.get("id") or ""
        if not draft_id:
            raise RuntimeError("Gmail API returned no draft id")
        return draft_id

    def _find_by_idempotency(self, calendar_id: str, key: str) -> Optional[str]:
        """Best-effort lookup of an existing hold with the same idempotency key."""
        try:

            def _call() -> Any:
                return (
                    self._clients.calendar.events()
                    .list(
                        calendarId=calendar_id,
                        privateExtendedProperty=[f"{_IDEM_PROP}={key}"],
                        maxResults=1,
                        singleEvents=True,
                    )
                    .execute()
                )

            result = with_retry(
                "calendar_idempotency_lookup",
                _call,
                correlation_id=self.correlation_id,
                retries=0,
            )
            items = result.get("items") or []
            if items:
                return items[0].get("id")
        except Exception:  # noqa: BLE001
            logger.debug("idempotency lookup skipped/failed for key=%s", key)
        return None

    def dispatch(self, name: str, arguments: dict) -> Any:
        """Dispatch a tool call by MCP tool name (used by Gemini agent)."""
        if name == "calendar_create_hold":
            return self.calendar_create_hold(
                title=arguments["title"],
                start_utc=arguments["start_utc"],
                end_utc=arguments["end_utc"],
                calendar_id=arguments.get("calendar_id") or self._config.calendar_id,
                idempotency_key=arguments["idempotency_key"],
            )
        if name == "calendar_delete_hold":
            self.calendar_delete_hold(
                event_id=arguments["event_id"],
                calendar_id=arguments.get("calendar_id") or self._config.calendar_id,
            )
            return {"ok": True}
        if name == "docs_append_prebooking":
            self.docs_append_prebooking(
                doc_id=arguments.get("doc_id") or self._config.docs_prebooking_id,
                line=arguments["line"],
                idempotency_key=arguments["idempotency_key"],
            )
            return {"ok": True}
        if name == "gmail_create_draft":
            return self.gmail_create_draft(
                to=arguments.get("to") or self._config.gmail_advisor_to,
                subject=arguments["subject"],
                body_markdown=arguments["body_markdown"],
            )
        raise ValueError(f"Unknown MCP tool: {name}")
