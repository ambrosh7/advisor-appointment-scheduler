"""IST display helpers for chat and (later) TTS."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from domain.models import TimeSlot

IST = ZoneInfo("Asia/Kolkata")

# Example: "Tuesday, 8 April 2026, 3:00 PM IST"
_LABEL_FMT = "%A, %-d %B %Y, %-I:%M %p IST"


def format_instant_ist(instant_utc: datetime) -> str:
    """Format a UTC instant for user-facing copy in IST."""
    if instant_utc.tzinfo is None:
        raise ValueError("instant_utc must be timezone-aware")
    local = instant_utc.astimezone(IST)
    # %-d / %-I are POSIX-only; provide a portable fallback for Windows.
    try:
        return local.strftime(_LABEL_FMT)
    except ValueError:
        day = str(local.day)
        hour12 = local.hour % 12 or 12
        ampm = "AM" if local.hour < 12 else "PM"
        return (
            f"{local.strftime('%A')}, {day} {local.strftime('%B %Y')}, "
            f"{hour12}:{local.strftime('%M')} {ampm} IST"
        )


def format_slot_for_user(slot: TimeSlot) -> str:
    """User-facing label for a slot (chat display / TTS readback)."""
    if slot.label_ist:
        return slot.label_ist
    return format_instant_ist(slot.start_utc)


def build_slot(start_utc: datetime, end_utc: datetime) -> TimeSlot:
    """Construct a TimeSlot with IST label derived from start."""
    return TimeSlot(
        start_utc=start_utc,
        end_utc=end_utc,
        label_ist=format_instant_ist(start_utc),
    )
