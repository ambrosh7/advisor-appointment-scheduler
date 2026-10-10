"""Serializable domain DTOs — no PII."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from domain.enums import BookingStatus, TimeWindow, Topic


@dataclass(frozen=True)
class TimeSlot:
    start_utc: datetime
    end_utc: datetime
    label_ist: str

    def to_dict(self) -> dict:
        return {
            "start_utc": self.start_utc.isoformat(),
            "end_utc": self.end_utc.isoformat(),
            "label_ist": self.label_ist,
        }


@dataclass
class BookingPreference:
    """May be partially filled while the session collects topic/time."""

    topic: Optional[Topic] = None
    preferred_date_ist: Optional[date] = None
    preferred_time_window: Optional[TimeWindow] = None
    raw_user_phrase: Optional[str] = None


@dataclass
class BookingRecord:
    code: str
    topic: Topic
    slot: TimeSlot
    created_at_utc: datetime
    status: BookingStatus
    calendar_event_id: Optional[str] = None
    customer_name: str = ""

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "topic": self.topic.value,
            "slot": self.slot.to_dict(),
            "created_at_utc": self.created_at_utc.isoformat(),
            "status": self.status.value,
            "calendar_event_id": self.calendar_event_id,
            "customer_name": self.customer_name,
        }
