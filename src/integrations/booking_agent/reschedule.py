"""Reschedule side effects — delete old calendar hold + create new (MCP)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Protocol

from domain.enums import Topic
from domain.models import TimeSlot
from integrations.booking_agent.execute import format_prebooking_line
from integrations.google_mcp.config import GoogleMcpConfig


@dataclass
class RescheduleExecutionRequest:
    topic: Topic
    old_slot: TimeSlot
    new_slot: TimeSlot
    booking_code: str
    old_calendar_event_id: Optional[str] = None
    correlation_id: str = ""
    calendar_id: str = "primary"
    doc_id: str = ""


@dataclass
class RescheduleExecutionResult:
    ok: bool
    booking_code: str
    calendar_event_id: Optional[str] = None
    tool_trace: List[str] = field(default_factory=list)
    error: Optional[str] = None


class ToolDispatcher(Protocol):
    def dispatch(self, name: str, arguments: dict) -> Any: ...


class RescheduleSideEffects(Protocol):
    def execute(self, request: RescheduleExecutionRequest) -> RescheduleExecutionResult: ...


class ExecuteRescheduleSideEffects:
    """Delete old hold + create new hold; append a Docs audit line."""

    def __init__(
        self,
        tools: ToolDispatcher,
        config: Optional[GoogleMcpConfig] = None,
    ) -> None:
        self._tools = tools
        self._config = config or GoogleMcpConfig.from_env()

    def execute(self, request: RescheduleExecutionRequest) -> RescheduleExecutionResult:
        cal_id = request.calendar_id or self._config.calendar_id
        doc_id = request.doc_id or self._config.docs_prebooking_id
        trace: List[str] = []
        new_event_id: Optional[str] = None

        try:
            if request.old_calendar_event_id:
                self._tools.dispatch(
                    "calendar_delete_hold",
                    {
                        "event_id": request.old_calendar_event_id,
                        "calendar_id": cal_id,
                    },
                )
                trace.append("calendar_delete_hold")

            title = (
                f"Advisor Q&A — {request.topic.value} — {request.booking_code}"
            )
            new_event_id = str(
                self._tools.dispatch(
                    "calendar_create_hold",
                    {
                        "title": title,
                        "start_utc": request.new_slot.start_utc.isoformat(),
                        "end_utc": request.new_slot.end_utc.isoformat(),
                        "calendar_id": cal_id,
                        "idempotency_key": f"reschedule:{request.booking_code}",
                    },
                )
            )
            trace.append("calendar_create_hold")

            if doc_id:
                line = (
                    format_prebooking_line(
                        code=request.booking_code,
                        topic=request.topic,
                        slot=request.new_slot,
                    )
                    + " | status=rescheduled"
                    + f" | prior_slot={request.old_slot.label_ist}"
                )
                self._tools.dispatch(
                    "docs_append_prebooking",
                    {
                        "doc_id": doc_id,
                        "line": line,
                        "idempotency_key": f"reschedule:{request.booking_code}",
                    },
                )
                trace.append("docs_append_prebooking")

            return RescheduleExecutionResult(
                ok=True,
                booking_code=request.booking_code,
                calendar_event_id=new_event_id,
                tool_trace=trace,
            )
        except Exception as exc:  # noqa: BLE001
            return RescheduleExecutionResult(
                ok=False,
                booking_code=request.booking_code,
                calendar_event_id=new_event_id,
                tool_trace=trace,
                error=f"{type(exc).__name__}: {exc}",
            )

    def __call__(self, request: RescheduleExecutionRequest) -> RescheduleExecutionResult:
        return self.execute(request)
