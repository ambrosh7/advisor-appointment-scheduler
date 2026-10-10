"""MockCalendarService slot picking."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from domain.calendar import MockCalendarService
from domain.clock import FixedClock
from domain.enums import TimeWindow, Topic
from domain.formatting import build_slot
from domain.models import BookingPreference

IST = ZoneInfo("Asia/Kolkata")


def _pref(
    *,
    day: date | None = None,
    window: TimeWindow | None = None,
) -> BookingPreference:
    return BookingPreference(
        topic=Topic.KYC_ONBOARDING,
        preferred_date_ist=day,
        preferred_time_window=window,
    )


def test_find_two_slots_returns_at_most_two() -> None:
    # Monday ~07:30 IST — before working hours
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))
    cal = MockCalendarService()
    slots = cal.find_two_slots(_pref(day=date(2026, 4, 6), window=TimeWindow.MORNING), clock)
    assert len(slots) == 2
    assert slots[0].start_utc < slots[1].start_utc
    assert "IST" in slots[0].label_ist


def test_two_slot_truncation_with_injected_list() -> None:
    starts = [
        datetime(2026, 4, 8, 3, 30, tzinfo=timezone.utc),
        datetime(2026, 4, 8, 4, 0, tzinfo=timezone.utc),
        datetime(2026, 4, 8, 4, 30, tzinfo=timezone.utc),
    ]
    injected = [build_slot(s, s + timedelta(minutes=30)) for s in starts]
    cal = MockCalendarService(injected_slots=injected)
    slots = cal.find_two_slots(_pref(), FixedClock(datetime(2026, 4, 1, tzinfo=timezone.utc)))
    assert len(slots) == 2
    assert slots[0].start_utc == starts[0]
    assert slots[1].start_utc == starts[1]


def test_empty_calendar_when_all_busy() -> None:
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))
    all_morning = MockCalendarService(max_slots=100).find_two_slots(
        _pref(day=date(2026, 4, 6), window=TimeWindow.MORNING), clock
    )
    assert all_morning  # day had availability before we mark busy

    cal = MockCalendarService()
    for s in all_morning:
        cal.mark_busy(s.start_utc)
    slots = cal.find_two_slots(_pref(day=date(2026, 4, 6), window=TimeWindow.MORNING), clock)
    assert slots == []


def test_empty_on_past_preferred_date() -> None:
    clock = FixedClock(datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc))
    cal = MockCalendarService()
    slots = cal.find_two_slots(_pref(day=date(2026, 4, 1)), clock)
    assert slots == []


def test_boundary_skips_weekend() -> None:
    clock = FixedClock(datetime(2026, 4, 4, 2, 0, tzinfo=timezone.utc))
    cal = MockCalendarService()
    slots = cal.find_two_slots(_pref(day=date(2026, 4, 4), window=TimeWindow.MORNING), clock)
    assert slots == []


def test_window_filters_afternoon() -> None:
    clock = FixedClock(datetime(2026, 4, 6, 2, 0, tzinfo=timezone.utc))
    cal = MockCalendarService()
    slots = cal.find_two_slots(
        _pref(day=date(2026, 4, 6), window=TimeWindow.AFTERNOON), clock
    )
    assert len(slots) == 2
    for slot in slots:
        hour = slot.start_utc.astimezone(IST).hour
        assert 12 <= hour < 17


def test_hold_waitlist_slot() -> None:
    cal = MockCalendarService()
    slot = cal.hold_waitlist_slot(_pref(day=date(2026, 4, 8)), "WL-A001")
    assert slot is not None
    assert "IST" in slot.label_ist


def test_injected_empty_list_means_waitlist_signal() -> None:
    cal = MockCalendarService(injected_slots=[])
    slots = cal.find_two_slots(_pref(), FixedClock(datetime(2026, 4, 6, tzinfo=timezone.utc)))
    assert slots == []
