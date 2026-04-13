"""Distributed rate limiter using a Redis sliding-window counter.

Uses a sorted set where each member is a unique call ID and its score is the
Unix timestamp of the call. Old members (outside the window) are removed
before counting, making it a true sliding window rather than a fixed bucket.

Algorithm: O(log N) per acquire — safe for high-throughput scenarios.

Key:  atlas:ratelimit:<name>
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from typing import Generator

from worker.config import get_settings
from worker.redis_client import get_redis

logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding-window rate limiter backed by Redis sorted sets.

    Args:
        name:           Unique limiter name (used as part of the Redis key).
        max_calls:      Maximum number of calls allowed per window.
        window_seconds: Length of the sliding window in seconds.
    """

    def __init__(
        self,
        name: str,
        max_calls: int | None = None,
        window_seconds: int | None = None,
    ) -> None:
        settings = get_settings()
        self._key = f"atlas:ratelimit:{name}"
        self._max_calls = max_calls if max_calls is not None else settings.rate_limit_calls
        self._window = window_seconds if window_seconds is not None else settings.rate_limit_window_seconds

    # ── Public API ────────────────────────────────────────────────────────────

    def acquire(self) -> bool:
        """Attempt to acquire a rate-limit slot.

        Returns True if the slot was granted, False if the limit is exceeded.
        Uses a Redis pipeline (single round-trip) for atomicity.
        """
        r = get_redis()
        now = time.time()
        window_start = now - self._window

        member = str(uuid.uuid4())

        pipe = r.pipeline()
        # Remove stale entries outside the window
        pipe.zremrangebyscore(self._key, "-inf", window_start)
        # Count remaining entries (calls in window)
        pipe.zcard(self._key)
        # Tentatively add this call
        pipe.zadd(self._key, {member: now})
        # Set key expiry to avoid orphaned keys
        pipe.expire(self._key, self._window * 2)
        results = pipe.execute()

        current_count = results[1]  # zcard result (before our zadd)

        if current_count < self._max_calls:
            return True  # our zadd is already in the set

        # Limit exceeded — remove the tentative entry we just added
        r.zrem(self._key, member)
        return False

    def wait_and_acquire(self, poll_interval: float = 0.5, timeout: float = 60.0) -> bool:
        """Block until a slot is available or timeout elapses.

        Returns True if acquired, False on timeout.
        Suitable for cases where dropping the job would be worse than waiting.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.acquire():
                return True
            time.sleep(poll_interval)
        logger.warning("rate_limiter_timeout key=%s max_calls=%d", self._key, self._max_calls)
        return False

    def remaining(self) -> int:
        """Return the number of slots available right now (approximate)."""
        r = get_redis()
        now = time.time()
        window_start = now - self._window
        r.zremrangebyscore(self._key, "-inf", window_start)
        used = r.zcard(self._key)
        return max(0, self._max_calls - used)

    def reset(self) -> None:
        """Clear the rate limiter (test helper; do not call in production)."""
        redis_client = get_redis()
        redis_client.delete(self._key)
        try:
            redis_client.zremrangebyscore(self._key, "-inf", "+inf")
        except Exception:
            pass


@contextmanager
def rate_limited(
    name: str,
    max_calls: int | None = None,
    window_seconds: int | None = None,
    timeout: float = 60.0,
) -> Generator[None, None, None]:
    """Context manager that blocks until a rate-limit slot is available.

    Raises RuntimeError if the timeout expires before a slot becomes free.

    Usage::

        with rate_limited("optimization_api", max_calls=10, window_seconds=1):
            call_expensive_api()
    """
    limiter = RateLimiter(name, max_calls=max_calls, window_seconds=window_seconds)
    acquired = limiter.wait_and_acquire(timeout=timeout)
    if not acquired:
        raise RuntimeError(
            f"Rate limit '{name}' not acquired within {timeout}s "
            f"(limit={limiter._max_calls}/{limiter._window}s)"
        )
    yield


# ── Per-task Celery rate limit helper ─────────────────────────────────────────
# Celery's built-in rate_limit= is per-worker, not distributed.
# Use this decorator on the task body for cross-worker enforcement.

def distributed_rate_limit(name: str, max_calls: int, window_seconds: int = 60):
    """Decorator: applies a distributed rate limit to a function.

    Wraps the decorated function with a blocking wait_and_acquire call.
    Works inside Celery task bodies (and anywhere else).
    """
    def decorator(fn):  # type: ignore[misc]
        import functools

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):  # type: ignore[misc]
            limiter = RateLimiter(name, max_calls=max_calls, window_seconds=window_seconds)
            if not limiter.wait_and_acquire():
                raise RuntimeError(f"Rate limit '{name}' timed out")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
