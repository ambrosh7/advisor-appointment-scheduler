"""Cancel side effects — calendar delete + Docs cancelled line + optional Gmail."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Protocol

from domain.enums import Topic
from domain.models import TimeSlot
from integrations.booking_agent.execute import advisor_email_body, format_prebooking_line
from integrations.google_mcp.config import GoogleMcpConfig


@dataclass
class CancelExecutionRequest:
    topic: Topic
    slot: TimeSlot
    booking_code: str
    calendar_event_id: Optional[str] = None
    correlation_id: str = ""
    calendar_id: str = "primary"
    doc_id: str = ""
    advisor_email: str = ""
    notify_advisor: bool = True


@dataclass
class CancelExecutionResult:
    ok: bool
    booking_code: str
    gmail_draft_id: Optional[str] = None
    tool_trace: List[str] = field(default_factory=list)
    error: Optional[str] = None


class ToolDispatcher(Protocol):
    def dispatch(self, name: str, arguments: dict) -> Any: ...


class CancelSideEffects(Protocol):
    def execute(self, request: CancelExecutionRequest) -> CancelExecutionResult: ...


class ExecuteCancelSideEffects:
    """calendar_delete_hold + Docs append “cancelled” + optional Gmail draft."""

    def __init__(
        self,
        tools: ToolDispatcher,
        config: Optional[GoogleMcpConfig] = None,
    ) -> None:
        self._tools = tools
        self._config = config or GoogleMcpConfig.from_env()

    def execute(self, request: CancelExecutionRequest) -> CancelExecutionResult:
        cal_id = request.calendar_id or self._config.calendar_id
        doc_id = request.doc_id or self._config.docs_prebooking_id
        to_addr = request.advisor_email or self._config.gmail_advisor_to
        secure_url = self._config.secure_link_for(request.booking_code)
        trace: List[str] = []
        draft_id: Optional[str] = None

        try:
            if request.calendar_event_id:
                self._tools.dispatch(
                    "calendar_delete_hold",
                    {
                        "event_id": request.calendar_event_id,
                        "calendar_id": cal_id,
                    },
                )
                trace.append("calendar_delete_hold")

            if doc_id:
                line = (
                    format_prebooking_line(
                        code=request.booking_code,
                        topic=request.topic,
                        slot=request.slot,
                    )
                    + " | status=cancelled"
                )
                self._tools.dispatch(
                    "docs_append_prebooking",
                    {
                        "doc_id": doc_id,
                        "line": line,
                        "idempotency_key": f"cancel:{request.booking_code}",
                    },
                )
                trace.append("docs_append_prebooking")

            if request.notify_advisor and to_addr:
                body = (
                    "## Cancelled tentative booking\n\n"
                    + advisor_email_body(
                        code=request.booking_code,
                        topic=request.topic,
                        slot=request.slot,
                        secure_url=secure_url,
                    ).replace("## Tentative advisor booking\n\n", "")
                )
                draft_id = self._tools.dispatch(
                    "gmail_create_draft",
                    {
                        "to": to_addr,
                        "subject": (
                            f"Advisor cancel {request.booking_code} — "
                            f"{request.topic.value}"
                        ),
                        "body_markdown": body,
                        "idempotency_key": f"cancel:{request.booking_code}",
                    },
                )
                trace.append("gmail_create_draft")
                draft_id = str(draft_id) if draft_id is not None else None

            return CancelExecutionResult(
                ok=True,
                booking_code=request.booking_code,
                gmail_draft_id=draft_id,
                tool_trace=trace,
            )
        except Exception as exc:  # noqa: BLE001
            return CancelExecutionResult(
                ok=False,
                booking_code=request.booking_code,
                gmail_draft_id=draft_id,
                tool_trace=trace,
                error=f"{type(exc).__name__}: {exc}",
            )

    def __call__(self, request: CancelExecutionRequest) -> CancelExecutionResult:
        return self.execute(request)
