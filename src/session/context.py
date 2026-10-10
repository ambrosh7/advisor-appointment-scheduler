"""Per-session context and agent turn result."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from domain.enums import AdvisorDisclaimerStatus, Intent
from domain.models import BookingPreference, TimeSlot
from session.states import State


@dataclass
class AgentTurn:
    messages: List[str] = field(default_factory=list)
    state: State = State.GREET
    session_id: str = ""


@dataclass
class SessionContext:
    session_id: str = field(default_factory=lambda: str(uuid4()))
    state: State = State.GREET
    disclaimer: AdvisorDisclaimerStatus = AdvisorDisclaimerStatus.PENDING
    customer_name: str = ""
    intent: Optional[Intent] = None
    preference: BookingPreference = field(default_factory=BookingPreference)
    offered_slots: List[TimeSlot] = field(default_factory=list)
    selected_slot: Optional[TimeSlot] = None
    pending_booking_code: Optional[str] = None
    calendar_event_id: Optional[str] = None
    gmail_draft_id: Optional[str] = None
    mcp_tool_trace: List[str] = field(default_factory=list)
    last_mcp_error: Optional[str] = None
    turn_count: int = 0
    advice_redirect_count: int = 0
    clarification_counts: dict = field(default_factory=dict)  # state -> count
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_assistant_question: str = ""

    def touch(self) -> None:
        self.last_active_utc = datetime.now(timezone.utc)

    def to_debug_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "disclaimer": self.disclaimer.value,
            "customer_name": self.customer_name or None,
            "intent": self.intent.value if self.intent else None,
            "topic": self.preference.topic.value if self.preference.topic else None,
            "preferred_date_ist": (
                self.preference.preferred_date_ist.isoformat()
                if self.preference.preferred_date_ist
                else None
            ),
            "preferred_time_window": (
                self.preference.preferred_time_window.value
                if self.preference.preferred_time_window
                else None
            ),
            "offered_slots": [s.to_dict() for s in self.offered_slots],
            "selected_slot": self.selected_slot.to_dict() if self.selected_slot else None,
            "pending_booking_code": self.pending_booking_code,
            "calendar_event_id": self.calendar_event_id,
            "gmail_draft_id": self.gmail_draft_id,
            "mcp_tool_trace": list(self.mcp_tool_trace),
            "last_mcp_error": self.last_mcp_error,
            "correlation_id": self.correlation_id,
            "turn_count": self.turn_count,
            "advice_redirect_count": self.advice_redirect_count,
            "clarification_counts": dict(self.clarification_counts),
        }
