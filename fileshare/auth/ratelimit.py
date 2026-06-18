"""In-memory sliding-window rate limiter keyed by (bucket, ip).

Good enough for a single-process app. Not shared across workers — run the
public server single-worker (we do).
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, bucket: str, ip: str, limit: int, window: float = 60.0) -> bool:
        """Return True if this hit is within the limit for the given window."""
        if limit <= 0:
            return True
        now = time.time()
        key = (bucket, ip)
        with self._lock:
            dq = self._hits[key]
            cutoff = now - window
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= limit:
                return False
            dq.append(now)
            return True


limiter = RateLimiter()
