"""IST formatting helpers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain.formatting import build_slot, format_instant_ist, format_slot_for_user
from domain.models import TimeSlot


def test_format_instant_ist_example_shape() -> None:
    # 2026-04-08 09:30 UTC == 15:00 IST
    instant = datetime(2026, 4, 8, 9, 30, tzinfo=timezone.utc)
    label = format_instant_ist(instant)
    assert "Wednesday" in label
    assert "8 April 2026" in label
    assert "3:00 PM IST" in label


def test_format_slot_for_user_uses_label() -> None:
    slot = TimeSlot(
        start_utc=datetime(2026, 4, 8, 9, 30, tzinfo=timezone.utc),
        end_utc=datetime(2026, 4, 8, 10, 0, tzinfo=timezone.utc),
        label_ist="Custom label IST",
    )
    assert format_slot_for_user(slot) == "Custom label IST"


def test_build_slot_sets_label() -> None:
    start = datetime(2026, 4, 8, 9, 30, tzinfo=timezone.utc)
    end = datetime(2026, 4, 8, 10, 0, tzinfo=timezone.utc)
    slot = build_slot(start, end)
    assert slot.label_ist == format_instant_ist(start)
    assert format_slot_for_user(slot) == slot.label_ist


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError):
        format_instant_ist(datetime(2026, 4, 8, 9, 30))
