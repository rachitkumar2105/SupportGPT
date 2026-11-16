"""In-process sliding-window rate limiter.

The Space runs a single uvicorn worker, so process memory is the source of
truth. With multiple workers or replicas this should move to Redis; the
interface (``hit(key, limit, window)``) stays the same.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def hit(self, key: str, limit: int, window_s: float) -> tuple[bool, float]:
        """Records a hit. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= limit:
                return False, max(0.0, q[0] + window_s - now)
            q.append(now)
            if now - self._last_sweep > 300:
                self._sweep(now)
            return True, 0.0

    def _sweep(self, now: float) -> None:
        # Drop keys idle for over an hour so memory stays bounded.
        for k in [k for k, q in self._hits.items() if not q or q[-1] < now - 3600]:
            del self._hits[k]
        self._last_sweep = now

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def enforce(key: str, limit: int, window_s: float) -> None:
    allowed, retry = limiter.hit(key, limit, window_s)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please slow down and try again shortly.",
            headers={"Retry-After": str(int(retry) + 1)},
        )
