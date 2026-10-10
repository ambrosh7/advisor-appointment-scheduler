"""Booking store interface and Phase 1 in-memory implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from domain.enums import BookingStatus
from domain.models import BookingRecord


class BookingStore(ABC):
    @abstractmethod
    def save(self, record: BookingRecord) -> None: ...

    @abstractmethod
    def get_by_code(self, code: str) -> Optional[BookingRecord]: ...

    @abstractmethod
    def update_status(self, code: str, status: BookingStatus) -> BookingRecord: ...

    @abstractmethod
    def exists(self, code: str) -> bool: ...


class InMemoryBookingStore(BookingStore):
    """Process-local dict store for Phases 1–2."""

    def __init__(self) -> None:
        self._records: dict[str, BookingRecord] = {}

    def save(self, record: BookingRecord) -> None:
        self._records[record.code] = record

    def get_by_code(self, code: str) -> Optional[BookingRecord]:
        return self._records.get(code)

    def update_status(self, code: str, status: BookingStatus) -> BookingRecord:
        record = self._records.get(code)
        if record is None:
            raise KeyError(f"Unknown booking code: {code}")
        record.status = status
        return record

    def exists(self, code: str) -> bool:
        return code in self._records

    def clear(self) -> None:
        self._records.clear()

    def __len__(self) -> int:
        return len(self._records)
