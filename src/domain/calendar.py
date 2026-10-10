"""Mock advisor calendar — pure in-memory slot picking (no I/O)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

from domain.clock import Clock, SystemClock
from domain.enums import TimeWindow
from domain.formatting import build_slot
from domain.models import BookingPreference, TimeSlot

IST = ZoneInfo("Asia/Kolkata")

# Advisor working hours in IST (hour starts that may host a slot).
_WORKING_START = time(9, 0)
_WORKING_END = time(20, 0)
_SLOT_MINUTES = 30
_LOOKAHEAD_DAYS = 14

_WINDOW_RANGES: dict[TimeWindow, tuple[time, time]] = {
    TimeWindow.MORNING: (time(9, 0), time(12, 0)),
    TimeWindow.AFTERNOON: (time(12, 0), time(17, 0)),
    TimeWindow.EVENING: (time(17, 0), time(20, 0)),
}


class MockCalendarService:
    """
    Deterministic slot finder for local dev/tests.

    Returns at most two free slots matching preference. Empty list means the
    orchestrator should take the waitlist path.
    """

    def __init__(
        self,
        *,
        injected_slots: Optional[Sequence[TimeSlot]] = None,
        busy: Optional[Iterable[datetime]] = None,
        max_slots: int = 2,
        slot_minutes: int = _SLOT_MINUTES,
        lookahead_days: int = _LOOKAHEAD_DAYS,
    ) -> None:
        self._injected = list(injected_slots) if injected_slots is not None else None
        self._busy: set[datetime] = {
            self._normalize_start(s) for s in (busy or [])
        }
        self._max_slots = max_slots
        self._slot_minutes = slot_minutes
        self._lookahead_days = lookahead_days

    def mark_busy(self, start_utc: datetime) -> None:
        self._busy.add(self._normalize_start(start_utc))

    def mark_free(self, start_utc: datetime) -> None:
        self._busy.discard(self._normalize_start(start_utc))

    def clear_busy(self) -> None:
        self._busy.clear()

    def find_two_slots(
        self,
        preference: BookingPreference,
        now: Optional[Clock] = None,
    ) -> list[TimeSlot]:
        """Return 0–2 free slots (never more than ``max_slots``)."""
        clock = now or SystemClock()
        if self._injected is not None:
            return list(self._injected)[: self._max_slots]

        candidates = self._generate_candidates(preference, clock.now())
        free = [s for s in candidates if self._normalize_start(s.start_utc) not in self._busy]
        return free[: self._max_slots]

    def peek_two_slots(
        self,
        preference: BookingPreference,
        now: Optional[Clock] = None,
    ) -> list[TimeSlot]:
        """
        Availability peek — same search as ``find_two_slots`` but never books
        or mutates busy state (Phase 6 ``check_availability``).
        """
        return self.find_two_slots(preference, now)

    def hold_waitlist_slot(
        self,
        preference: BookingPreference,
        code: str,
    ) -> Optional[TimeSlot]:
        """
        Synthetic waitlist marker: next working-day 09:00 IST after preferred date
        (or tomorrow IST if no date). ``code`` is unused but kept for API symmetry.
        """
        _ = code
        base_date = preference.preferred_date_ist or (
            datetime.now(IST).date() + timedelta(days=1)
        )
        # Skip weekends for the marker
        while base_date.weekday() >= 5:
            base_date += timedelta(days=1)
        start_local = datetime.combine(base_date, time(9, 0), tzinfo=IST)
        end_local = start_local + timedelta(minutes=self._slot_minutes)
        return build_slot(
            start_local.astimezone(ZoneInfo("UTC")),
            end_local.astimezone(ZoneInfo("UTC")),
        )

    def _generate_candidates(
        self,
        preference: BookingPreference,
        now_utc: datetime,
    ) -> list[TimeSlot]:
        if now_utc.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        now_ist = now_utc.astimezone(IST)
        start_day = preference.preferred_date_ist or now_ist.date()
        if start_day < now_ist.date():
            return []

        days: list[date]
        if preference.preferred_date_ist is not None:
            days = [preference.preferred_date_ist]
        else:
            days = [start_day + timedelta(days=i) for i in range(self._lookahead_days)]

        window = preference.preferred_time_window
        slots: list[TimeSlot] = []
        for day in days:
            if day.weekday() >= 5:  # Sat/Sun
                continue
            for start_local in self._day_starts(day, window):
                if start_local <= now_ist:
                    continue
                end_local = start_local + timedelta(minutes=self._slot_minutes)
                slots.append(
                    build_slot(
                        start_local.astimezone(ZoneInfo("UTC")),
                        end_local.astimezone(ZoneInfo("UTC")),
                    )
                )
        return slots

    def _day_starts(
        self,
        day: date,
        window: Optional[TimeWindow],
    ) -> list[datetime]:
        if window is TimeWindow.EXACT or window is None:
            win_start, win_end = _WORKING_START, _WORKING_END
        else:
            win_start, win_end = _WINDOW_RANGES[window]

        starts: list[datetime] = []
        cursor = datetime.combine(day, win_start, tzinfo=IST)
        end_bound = datetime.combine(day, win_end, tzinfo=IST)
        step = timedelta(minutes=self._slot_minutes)
        while cursor + step <= end_bound:
            starts.append(cursor)
            cursor += step
        return starts

    @staticmethod
    def _normalize_start(instant: datetime) -> datetime:
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=ZoneInfo("UTC"))
        return instant.astimezone(ZoneInfo("UTC")).replace(microsecond=0)
