"""Shared-password login with stateless HMAC-signed session tokens (stdlib only)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from collections import defaultdict, deque

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{2,32}$")


def normalize_username(raw: str) -> str | None:
    name = raw.strip().lower()
    return name if USERNAME_RE.fullmatch(name) else None


def check_password(supplied: str, expected: str) -> bool:
    return hmac.compare_digest(supplied.encode(), expected.encode())


def _sign(data: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()


def make_token(username: str, secret: str, ttl_seconds: int, now: float | None = None) -> str:
    expiry = int((now if now is not None else time.time()) + ttl_seconds)
    body = base64.urlsafe_b64encode(f"{username}|{expiry}".encode()).decode()
    return f"{body}.{_sign(body.encode(), secret)}"


def verify_token(token: str, secret: str, now: float | None = None) -> str | None:
    """Returns the username, or None if the token is malformed, tampered with or expired."""
    try:
        body, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, _sign(body.encode(), secret)):
            return None
        username, expiry = base64.urlsafe_b64decode(body.encode()).decode().rsplit("|", 1)
        if (now if now is not None else time.time()) > int(expiry):
            return None
        return username
    except Exception:
        return None


class LoginThrottle:
    """Blocks a client after too many failed logins in a window (in-memory, per process)."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 300):
        self.max_failures, self.window = max_failures, window_seconds
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._fails[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, key: str, now: float | None = None) -> bool:
        return len(self._prune(key, now if now is not None else time.time())) >= self.max_failures

    def record_failure(self, key: str, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self._prune(key, now).append(now)
