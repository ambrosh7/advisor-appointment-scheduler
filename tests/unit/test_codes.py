"""BookingCodeGenerator and spelling helpers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain.codes import CODE_PATTERN, BookingCodeGenerator, to_spelling
from domain.enums import BookingStatus, Topic
from domain.formatting import build_slot
from domain.models import BookingRecord
from domain.store import InMemoryBookingStore


def test_generate_matches_pattern() -> None:
    gen = BookingCodeGenerator(seed=42)
    code = gen.generate()
    assert CODE_PATTERN.match(code)


def test_generate_deterministic_with_seed() -> None:
    a = BookingCodeGenerator(seed=7).generate()
    b = BookingCodeGenerator(seed=7).generate()
    assert a == b


def test_uniqueness_retries_on_collision() -> None:
    store = InMemoryBookingStore()
    first = BookingCodeGenerator(store, seed=1).generate()
    start = datetime(2026, 4, 8, 9, 30, tzinfo=timezone.utc)
    end = datetime(2026, 4, 8, 10, 0, tzinfo=timezone.utc)
    store.save(
        BookingRecord(
            code=first,
            topic=Topic.KYC_ONBOARDING,
            slot=build_slot(start, end),
            created_at_utc=datetime.now(timezone.utc),
            status=BookingStatus.TENTATIVE,
        )
    )

    # Same seed would redraw ``first``; generator must retry and return a new code.
    second = BookingCodeGenerator(store, seed=1, max_retries=5).generate()
    assert second != first
    assert CODE_PATTERN.match(second)
    assert not store.exists(second)


def test_collision_retry_exhausted() -> None:
    class AlwaysTaken:
        def exists(self, code: str) -> bool:
            return True

    gen = BookingCodeGenerator(AlwaysTaken(), seed=0, max_retries=3)
    with pytest.raises(RuntimeError, match="Unable to generate unique"):
        gen.generate()


def test_to_spelling() -> None:
    assert to_spelling("NL-A742") == "N L dash A seven four two"
    assert to_spelling("ab-c001") == "A B dash C zero zero one"
