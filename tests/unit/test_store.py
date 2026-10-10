"""In-memory BookingStore."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain.enums import BookingStatus, Topic
from domain.formatting import build_slot
from domain.models import BookingRecord
from domain.store import InMemoryBookingStore


def _record(code: str = "NL-A742") -> BookingRecord:
    start = datetime(2026, 4, 8, 9, 30, tzinfo=timezone.utc)
    end = datetime(2026, 4, 8, 10, 0, tzinfo=timezone.utc)
    return BookingRecord(
        code=code,
        topic=Topic.SIP_MANDATES,
        slot=build_slot(start, end),
        created_at_utc=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
        status=BookingStatus.TENTATIVE,
    )


def test_save_and_get() -> None:
    store = InMemoryBookingStore()
    rec = _record()
    store.save(rec)
    assert store.get_by_code("NL-A742") is rec
    assert store.exists("NL-A742")
    assert store.get_by_code("XX-X000") is None


def test_update_status() -> None:
    store = InMemoryBookingStore()
    store.save(_record())
    updated = store.update_status("NL-A742", BookingStatus.CANCELLED)
    assert updated.status is BookingStatus.CANCELLED
    assert store.get_by_code("NL-A742").status is BookingStatus.CANCELLED


def test_update_missing_raises() -> None:
    store = InMemoryBookingStore()
    with pytest.raises(KeyError):
        store.update_status("ZZ-Z999", BookingStatus.CANCELLED)
