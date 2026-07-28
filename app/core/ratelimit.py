"""A minimal in-memory per-IP fixed-window rate limiter.

Single-instance only (state lives in this process) — enough to blunt abuse of
the demo API. A multi-instance deployment would move this to Redis. Thread-safe
so it works under Starlette's threadpool.
"""

from __future__ import annotations

import threading


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.limit = per_minute  # 0 disables limiting
        self._lock = threading.Lock()
        # key -> (window_start_epoch_minute, count)
        self._buckets: dict[str, tuple[int, int]] = {}

    def check(self, key: str, now_seconds: float) -> bool:
        """Return True if the request is allowed, False if the key is over its
        per-minute budget. ``now_seconds`` is passed in (monotonic clock) so the
        caller controls the time source."""
        if self.limit <= 0:
            return True
        window = int(now_seconds // 60)
        with self._lock:
            start, count = self._buckets.get(key, (window, 0))
            if start != window:  # new minute → reset
                start, count = window, 0
            count += 1
            self._buckets[key] = (start, count)
            # Opportunistic cleanup so the dict can't grow unbounded.
            if len(self._buckets) > 10_000:
                self._buckets = {
                    k: v for k, v in self._buckets.items() if v[0] == window
                }
            return count <= self.limit
