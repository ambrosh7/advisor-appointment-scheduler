"""Session store with idle TTL."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Optional

from session.context import SessionContext

DEFAULT_TTL = timedelta(minutes=30)


class SessionStore(ABC):
    @abstractmethod
    def get(self, session_id: str) -> Optional[SessionContext]: ...

    @abstractmethod
    def put(self, session: SessionContext) -> None: ...

    @abstractmethod
    def delete(self, session_id: str) -> None: ...

    @abstractmethod
    def purge_expired(self) -> int:
        """Evict idle sessions; return count removed (TTL job + lazy paths)."""
        ...


class InMemorySessionStore(SessionStore):
    """Thread-safe dict store with idle TTL eviction on read/write."""

    def __init__(self, ttl: timedelta = DEFAULT_TTL) -> None:
        self._ttl = ttl
        self._lock = threading.RLock()
        self._sessions: dict[str, SessionContext] = {}

    def get(self, session_id: str) -> Optional[SessionContext]:
        with self._lock:
            self._evict_expired()
            return self._sessions.get(session_id)

    def put(self, session: SessionContext) -> None:
        with self._lock:
            self._evict_expired()
            session.touch()
            self._sessions[session.session_id] = session

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def purge_expired(self) -> int:
        with self._lock:
            return self._evict_expired()

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)

    def _evict_expired(self) -> int:
        now = datetime.now(timezone.utc)
        expired = [
            sid
            for sid, s in self._sessions.items()
            if now - s.last_active_utc > self._ttl
        ]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)
