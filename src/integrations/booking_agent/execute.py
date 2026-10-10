"""ExecuteBookingSideEffects use case — Gemini agent + Google MCP tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Protocol

from domain.enums import Topic
from domain.models import TimeSlot


@dataclass
class BookingExecutionRequest:
    topic: Topic
    slot: TimeSlot
    booking_code: str
    correlation_id: str = ""
    calendar_id: str = "primary"
    doc_id: str = ""
    advisor_email: str = ""
    customer_name: str = ""


@dataclass
class BookingExecutionResult:
    ok: bool
    booking_code: str
    secure_url: str = ""
    calendar_event_id: Optional[str] = None
    gmail_draft_id: Optional[str] = None
    tool_trace: List[str] = field(default_factory=list)
    error: Optional[str] = None
    # Phase 8: MCP outage → Gmail-only queue; booking not confirmed
    degraded: bool = False
    degraded_gmail_ok: bool = False


class BookingSideEffects(Protocol):
    def execute(self, request: BookingExecutionRequest) -> BookingExecutionResult: ...


class ExecuteBookingSideEffects:
    """
    Invoked from BOOK_EXECUTE_MCP.

    Delegates tool calling to the Gemini booking agent, which must invoke the
    three actual Google MCP tools (calendar, docs, gmail).
    """

    def __init__(self, agent: BookingSideEffects) -> None:
        self._agent = agent

    def execute(self, request: BookingExecutionRequest) -> BookingExecutionResult:
        return self._agent.execute(request)

    def __call__(self, request: BookingExecutionRequest) -> BookingExecutionResult:
        return self.execute(request)


def format_prebooking_line(
    *,
    code: str,
    topic: Topic,
    slot: TimeSlot,
    created_at_utc: Optional[datetime] = None,
    customer_name: str = "",
) -> str:
    when = slot.label_ist
    created_dt = created_at_utc or datetime.now(timezone.utc)
    created = created_dt.astimezone(timezone.utc).isoformat()
    name_part = f" | name={customer_name}" if customer_name else ""
    return (
        f"{created} | code={code}{name_part} | topic={topic.value} | slot={when} | "
        f"start_utc={slot.start_utc.isoformat()} | end_utc={slot.end_utc.isoformat()}"
    )


def advisor_email_body(
    *,
    code: str,
    topic: Topic,
    slot: TimeSlot,
    secure_url: str,
    customer_name: str = "",
) -> str:
    name_line = f"- **Name:** {customer_name}\n" if customer_name else ""
    return (
        f"## Tentative advisor booking\n\n"
        f"- **Code:** {code}\n"
        f"{name_line}"
        f"- **Topic:** {topic.value}\n"
        f"- **Slot (IST):** {slot.label_ist}\n"
        f"- **Secure details link:** {secure_url}\n\n"
        f"_Draft only — do not send until approved._\n"
    )
