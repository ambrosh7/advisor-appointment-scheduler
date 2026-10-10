"""Session TTL purge job."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ops.ttl_job import SessionTtlJob
from session.context import SessionContext
from session.store import InMemorySessionStore


def test_purge_expired_removes_idle_sessions() -> None:
    store = InMemorySessionStore(ttl=timedelta(seconds=1))
    s = SessionContext()
    store.put(s)
    s.last_active_utc = datetime.now(timezone.utc) - timedelta(seconds=5)
    # put() would touch — write directly into internal map for idle simulation
    with store._lock:  # noqa: SLF001
        store._sessions[s.session_id] = s  # noqa: SLF001

    job = SessionTtlJob(store, interval_s=3600)
    assert job.sweep_once() == 1
    assert store.get(s.session_id) is None


def test_job_start_stop() -> None:
    store = InMemorySessionStore()
    job = SessionTtlJob(store, interval_s=3600)
    job.start()
    assert job.running
    job.stop()
    assert not job.running
