"""Background session TTL sweep — shared by chat and voice surfaces."""

from __future__ import annotations

import logging
import threading
from typing import Optional, Protocol

logger = logging.getLogger(__name__)


class SupportsPurge(Protocol):
    def purge_expired(self) -> int: ...


class SessionTtlJob:
    """
    Periodically purge idle sessions.

    Eviction also runs lazily on get/put; this job keeps memory bounded when
    clients abandon sessions without further reads.
    """

    def __init__(
        self,
        store: SupportsPurge,
        *,
        interval_s: float = 60.0,
        name: str = "session-ttl",
    ) -> None:
        self._store = store
        self._interval = max(1.0, interval_s)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._name = name
        self.last_purged: int = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=self._name, daemon=True
        )
        self._thread.start()
        logger.info(
            "session_ttl_job started interval_s=%s",
            self._interval,
            extra={"correlation_id": "-", "event": "ttl_job_start"},
        )

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
            self._thread = None

    def sweep_once(self) -> int:
        purged = self._store.purge_expired()
        self.last_purged = purged
        if purged:
            logger.info(
                "session_ttl_job purged=%s",
                purged,
                extra={"correlation_id": "-", "event": "ttl_purge"},
            )
        return purged

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.sweep_once()
            except Exception:  # noqa: BLE001
                logger.exception("session_ttl_job sweep failed")
            self._stop.wait(self._interval)
