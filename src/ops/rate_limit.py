"""Sliding-window rate limiter (session create, shared chat/voice)."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_s: float = 0.0
    remaining: int = 0


class SlidingWindowRateLimiter:
    """
    Per-key sliding window.

    Default key is client IP / ``global`` for single-tenant demos.
    """

    def __init__(self, *, limit: int = 30, window_s: float = 60.0) -> None:
        self._limit = max(1, limit)
        self._window = max(0.1, window_s)
        self._lock = threading.Lock()
        self._hits: Dict[str, Deque[float]] = {}

    def allow(self, key: str = "global") -> RateLimitResult:
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            cutoff = now - self._window
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self._limit:
                retry = max(0.0, self._window - (now - q[0]))
                return RateLimitResult(
                    allowed=False, retry_after_s=retry, remaining=0
                )
            q.append(now)
            return RateLimitResult(
                allowed=True,
                remaining=max(0, self._limit - len(q)),
            )

    def reset(self, key: Optional[str] = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)
