"""Daily question quota per user plus a global ceiling.

Counts come from the audit log, so limits survive restarts and are shared across workers.
In-flight requests are tracked in memory so parallel requests cannot all slip under the limit.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from contextlib import contextmanager
from typing import Callable, Iterator


class RateLimitExceeded(Exception):
    def __init__(self, scope: str, message: str):
        super().__init__(message)
        self.scope = scope      # "user" | "global"
        self.message = message


class DailyLimiter:
    def __init__(self, count_today: Callable[[str | None], int], per_user: int, global_limit: int):
        self.count_today, self.per_user, self.global_limit = count_today, per_user, global_limit
        self._lock = threading.Lock()
        self._inflight: dict[str, int] = defaultdict(int)

    def remaining(self, user: str) -> int:
        with self._lock:
            return max(0, self.per_user - self.count_today(user) - self._inflight[user])

    @contextmanager
    def reserve(self, user: str) -> Iterator[None]:
        with self._lock:
            if self.count_today(None) + sum(self._inflight.values()) >= self.global_limit:
                raise RateLimitExceeded("global", "The team's daily question limit has been reached. Try again after 00:00 UTC.")
            if self.count_today(user) + self._inflight[user] >= self.per_user:
                raise RateLimitExceeded("user", f"You have used all {self.per_user} questions for today (resets 00:00 UTC).")
            self._inflight[user] += 1
        try:
            yield
        finally:
            with self._lock:
                self._inflight[user] -= 1
