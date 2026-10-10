"""Direct booking executor — calendar/docs/gmail without Gemini tool-calling."""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Protocol

from integrations.booking_agent.execute import (
    BookingExecutionRequest,
    BookingExecutionResult,
    advisor_email_body,
    format_prebooking_line,
)
from integrations.google_mcp.config import GoogleMcpConfig

logger = logging.getLogger(__name__)


class ToolDispatcher(Protocol):
    def dispatch(self, name: str, arguments: dict) -> Any: ...


class DirectBookingSideEffects:
    """
    Deterministic booking path used when the Gemini agent is unavailable
    (quota, timeout, etc.). Same three MCP tools, no LLM.
    """

    def __init__(
        self,
        tools: ToolDispatcher,
        config: Optional[GoogleMcpConfig] = None,
    ) -> None:
        self._tools = tools
        self._config = config or GoogleMcpConfig.from_env()

    def execute(self, request: BookingExecutionRequest) -> BookingExecutionResult:
        secure_url = self._config.secure_link_for(request.booking_code)
        trace: List[str] = []
        calendar_event_id: Optional[str] = None
        gmail_draft_id: Optional[str] = None
        name_bit = f" — {request.customer_name}" if request.customer_name else ""
        title = (
            f"Advisor Q&A — {request.topic.value} — {request.booking_code}{name_bit}"
        )
        cal_id = request.calendar_id or self._config.calendar_id
        doc_id = request.doc_id or self._config.docs_prebooking_id
        to_addr = request.advisor_email or self._config.gmail_advisor_to

        try:
            calendar_event_id = str(
                self._tools.dispatch(
                    "calendar_create_hold",
                    {
                        "title": title,
                        "start_utc": request.slot.start_utc.isoformat(),
                        "end_utc": request.slot.end_utc.isoformat(),
                        "calendar_id": cal_id,
                        "idempotency_key": f"booking:{request.booking_code}",
                    },
                )
            )
            trace.append("calendar_create_hold")

            line = format_prebooking_line(
                code=request.booking_code,
                topic=request.topic,
                slot=request.slot,
                customer_name=request.customer_name,
            )
            self._tools.dispatch(
                "docs_append_prebooking",
                {
                    "doc_id": doc_id,
                    "line": line,
                    "idempotency_key": f"booking:{request.booking_code}",
                },
            )
            trace.append("docs_append_prebooking")

            if not to_addr:
                raise RuntimeError("GOOGLE_GMAIL_ADVISOR_TO is not configured")

            subject = (
                f"Tentative advisor booking {request.booking_code} — "
                f"{request.topic.value}"
            )
            if request.customer_name:
                subject += f" — {request.customer_name}"
            gmail_draft_id = str(
                self._tools.dispatch(
                    "gmail_create_draft",
                    {
                        "to": to_addr,
                        "subject": subject,
                        "body_markdown": advisor_email_body(
                            code=request.booking_code,
                            topic=request.topic,
                            slot=request.slot,
                            secure_url=secure_url,
                            customer_name=request.customer_name,
                        ),
                        "idempotency_key": f"booking:{request.booking_code}",
                    },
                )
            )
            trace.append("gmail_create_draft")

            logger.info(
                "direct_booking_ok code=%s calendar=%s",
                request.booking_code,
                calendar_event_id,
                extra={
                    "correlation_id": request.correlation_id or "-",
                    "event": "direct_booking_ok",
                },
            )
            return BookingExecutionResult(
                ok=True,
                booking_code=request.booking_code,
                secure_url=secure_url,
                calendar_event_id=calendar_event_id,
                gmail_draft_id=gmail_draft_id,
                tool_trace=trace,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "direct_booking_failed code=%s err=%s",
                request.booking_code,
                type(exc).__name__,
                extra={
                    "correlation_id": request.correlation_id or "-",
                    "event": "direct_booking_failed",
                },
            )
            if calendar_event_id:
                try:
                    self._tools.dispatch(
                        "calendar_delete_hold",
                        {
                            "event_id": calendar_event_id,
                            "calendar_id": cal_id,
                        },
                    )
                    trace.append("calendar_delete_hold")
                except Exception:  # noqa: BLE001
                    logger.exception("direct booking compensation delete failed")
            return BookingExecutionResult(
                ok=False,
                booking_code=request.booking_code,
                secure_url=secure_url,
                calendar_event_id=None,
                gmail_draft_id=gmail_draft_id,
                tool_trace=trace,
                error=f"{type(exc).__name__}: {exc}",
            )
