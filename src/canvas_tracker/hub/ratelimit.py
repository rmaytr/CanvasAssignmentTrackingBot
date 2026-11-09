"""Per-user sliding-window rate limits (token checks, manual /sync).

Kept in memory: a restart forgets them, which is fine for limits measured in
minutes. Each user only ever has their own handful of timestamps, and users
whose window has passed are dropped, so the state stays small.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta


class RateLimiter:
    """At most ``limit`` hits per user in any ``window``. The caller passes the time."""

    def __init__(self, limit: int, window: timedelta) -> None:
        if limit < 1 or window <= timedelta(0):
            raise ValueError("a rate limit needs a positive limit and window")
        self.limit = limit
        self.window = window
        self._hits: dict[int, deque[datetime]] = {}

    def _recent(self, key: int, now: datetime) -> deque[datetime]:
        hits = self._hits.get(key)
        if hits is None:
            return deque()
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if not hits:
            del self._hits[key]
        return hits

    def wait(self, key: int, now: datetime) -> timedelta | None:
        """How long until ``key`` may go again, or None if it may go now. Records nothing."""
        hits = self._recent(key, now)
        if len(hits) < self.limit:
            return None
        return hits[0] + self.window - now

    def hit(self, key: int, now: datetime) -> timedelta | None:
        """Record an attempt if it's allowed (returns None); otherwise return the wait."""
        wait = self.wait(key, now)
        if wait is not None:
            return wait
        self._hits.setdefault(key, deque()).append(now)
        return None

    def __len__(self) -> int:
        """How many users currently have hits on record (for tests and sanity checks)."""
        return len(self._hits)
