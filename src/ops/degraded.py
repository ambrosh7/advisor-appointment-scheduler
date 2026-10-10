"""
Degraded MCP mode: queue Gmail draft only, ask user to retry.

Used when Calendar/Docs (or the full booking agent) fails. Same user-facing
strings for chat and voice (orchestrator copy).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional, Protocol

from integrations.booking_agent.execute import (
    BookingExecutionRequest,
    BookingExecutionResult,
    advisor_email_body,
)
from integrations.google_mcp.config import GoogleMcpConfig

logger = logging.getLogger(__name__)


class ToolDispatcher(Protocol):
    def dispatch(self, name: str, arguments: dict) -> Any: ...


@dataclass
class DegradedQueueResult:
    ok: bool
    gmail_draft_id: Optional[str] = None
    tool_trace: List[str] = field(default_factory=list)
    error: Optional[str] = None


class GmailOnlyDegradedQueue:
    """
    Runbook action for Google MCP outage:

    1. Attempt ``gmail_create_draft`` with booking details (advisor queue)
    2. Do **not** mark the booking confirmed — caller tells user to retry
    """

    def __init__(
        self,
        tools: ToolDispatcher,
        config: Optional[GoogleMcpConfig] = None,
    ) -> None:
        self._tools = tools
        self._config = config or GoogleMcpConfig.from_env()

    @property
    def config(self) -> GoogleMcpConfig:
        return self._config

    def queue_advisor_draft(
        self, request: BookingExecutionRequest
    ) -> DegradedQueueResult:
        secure_url = self._config.secure_link_for(request.booking_code)
        to_addr = request.advisor_email or self._config.gmail_advisor_to
        if not to_addr:
            return DegradedQueueResult(
                ok=False, error="GOOGLE_GMAIL_ADVISOR_TO is not configured"
            )

        name_bit = f" — {request.customer_name}" if request.customer_name else ""
        subject = (
            f"[DEGRADED] Advisor booking retry needed "
            f"{request.booking_code} — {request.topic.value}{name_bit}"
        )
        body = (
            "## Degraded mode — calendar/docs unavailable\n\n"
            "Full MCP booking failed. Please retry the calendar hold manually "
            "or ask the user to confirm again in chat/voice.\n\n"
            + advisor_email_body(
                code=request.booking_code,
                topic=request.topic,
                slot=request.slot,
                secure_url=secure_url,
                customer_name=request.customer_name,
            )
        )
        trace: List[str] = []
        try:
            draft_id = self._tools.dispatch(
                "gmail_create_draft",
                {
                    "to": to_addr,
                    "subject": subject,
                    "body_markdown": body,
                    "idempotency_key": f"degraded:{request.booking_code}",
                },
            )
            trace.append("gmail_create_draft")
            logger.warning(
                "degraded_mode queued gmail draft booking_code=%s correlation_id=%s",
                request.booking_code,
                request.correlation_id,
                extra={
                    "correlation_id": request.correlation_id or "-",
                    "event": "mcp_degraded_gmail_queued",
                },
            )
            return DegradedQueueResult(
                ok=True,
                gmail_draft_id=str(draft_id) if draft_id is not None else None,
                tool_trace=trace,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "degraded_mode gmail queue failed correlation_id=%s err=%s",
                request.correlation_id,
                type(exc).__name__,
                extra={
                    "correlation_id": request.correlation_id or "-",
                    "event": "mcp_degraded_gmail_failed",
                },
            )
            return DegradedQueueResult(
                ok=False,
                tool_trace=trace,
                error=f"{type(exc).__name__}: {exc}",
            )


class ResilientBookingSideEffects:
    """
    Gemini agent → direct tools fallback → Gmail-only degraded queue.

    Direct path keeps calendar holds working when Gemini is rate-limited.
    """

    def __init__(
        self,
        primary: Any,
        degraded: GmailOnlyDegradedQueue,
        *,
        direct: Any = None,
    ) -> None:
        self._primary = primary
        self._degraded = degraded
        self._direct = direct

    def execute(self, request: BookingExecutionRequest) -> BookingExecutionResult:
        result = self._primary.execute(request)
        if result.ok:
            return result

        trace = list(result.tool_trace)
        last_error = result.error

        if self._direct is not None:
            direct_result = self._direct.execute(request)
            trace.extend(direct_result.tool_trace)
            trace.append("direct_booking_fallback")
            if direct_result.ok:
                direct_result.tool_trace = trace
                return direct_result
            last_error = direct_result.error or last_error

        queued = self._degraded.queue_advisor_draft(request)
        trace = trace + list(queued.tool_trace)
        if queued.tool_trace:
            trace.append("degraded_gmail_queue")
        secure = result.secure_url or self._degraded.config.secure_link_for(
            request.booking_code
        )
        return BookingExecutionResult(
            ok=False,
            booking_code=request.booking_code,
            secure_url=secure,
            calendar_event_id=result.calendar_event_id,
            gmail_draft_id=queued.gmail_draft_id or result.gmail_draft_id,
            tool_trace=trace,
            error=last_error,
            degraded=True,
            degraded_gmail_ok=queued.ok,
        )
