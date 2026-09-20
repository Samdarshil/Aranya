"""
In-memory rate limiter — spec section 19.

STATUS: real and tested for a single-process deployment. This does NOT
coordinate across multiple backend instances/workers — a real production
deployment behind more than one process needs a shared store (Redis is
the standard choice) instead of this in-memory dict. That swap should
only require a different implementation of the same `allow()` method;
nothing that calls this class needs to change. Labeled honestly rather
than presented as production-ready for a scaled deployment.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass
class SlidingWindowRateLimiter:
    max_requests: int
    window_seconds: float
    _hits: dict[str, deque] = field(default_factory=lambda: defaultdict(deque))

    def allow(self, key: str) -> bool:
        """Returns True and records the hit if `key` is under its limit
        for the current window; returns False (and does NOT record a hit)
        if the limit is already reached."""
        now = time.monotonic()
        window = self._hits[key]
        cutoff = now - self.window_seconds
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= self.max_requests:
            return False
        window.append(now)
        return True

    def remaining(self, key: str) -> int:
        now = time.monotonic()
        window = self._hits[key]
        cutoff = now - self.window_seconds
        while window and window[0] < cutoff:
            window.popleft()
        return max(0, self.max_requests - len(window))
