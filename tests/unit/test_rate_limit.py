"""Session-create rate limiter."""

from __future__ import annotations

from ops.rate_limit import SlidingWindowRateLimiter


def test_allows_until_limit_then_blocks() -> None:
    lim = SlidingWindowRateLimiter(limit=3, window_s=60.0)
    assert lim.allow("a").allowed
    assert lim.allow("a").allowed
    assert lim.allow("a").allowed
    blocked = lim.allow("a")
    assert not blocked.allowed
    assert blocked.retry_after_s > 0


def test_keys_are_independent() -> None:
    lim = SlidingWindowRateLimiter(limit=1, window_s=60.0)
    assert lim.allow("x").allowed
    assert not lim.allow("x").allowed
    assert lim.allow("y").allowed
