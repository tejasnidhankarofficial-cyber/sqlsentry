from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import LoginThrottle, make_token, verify_token
from app.config import Settings
from app.execute import QueryResult
from app.main import create_app
from app.pipeline import Answer
from app.ratelimit import DailyLimiter, RateLimitExceeded


# ---------- tokens ----------
def test_token_roundtrip():
    assert verify_token(make_token("alice", "s", 60), "s") == "alice"


def test_token_wrong_secret_expired_and_tampered():
    t = make_token("alice", "s", 60, now=1000)
    assert verify_token(t, "other") is None
    assert verify_token(t, "s", now=1000 + 61) is None
    body, sig = t.rsplit(".", 1)
    assert verify_token(body + "x." + sig, "s") is None
    assert verify_token("garbage", "s") is None


def test_login_throttle():
    th = LoginThrottle(max_failures=3, window_seconds=10)
    for _ in range(3):
        th.record_failure("ip", now=0)
    assert th.blocked("ip", now=5)
    assert not th.blocked("ip", now=11)       # window passed
    assert not th.blocked("other-ip", now=5)


# ---------- limiter ----------
def fake_counts(per_user: dict, total_extra=0):
    return lambda u: sum(per_user.values()) + total_extra if u is None else per_user.get(u, 0)


def test_user_limit_enforced():
    lim = DailyLimiter(fake_counts({"a": 2}), per_user=2, global_limit=100)
    with pytest.raises(RateLimitExceeded) as e:
        with lim.reserve("a"):
            pass
    assert e.value.scope == "user"
    with lim.reserve("b"):                    # other users unaffected
        pass


def test_global_limit_enforced():
    lim = DailyLimiter(fake_counts({"a": 1, "b": 1}), per_user=50, global_limit=2)
    with pytest.raises(RateLimitExceeded) as e:
        with lim.reserve("c"):
            pass
    assert e.value.scope == "global"


def test_inflight_requests_count_against_limit():
    lim = DailyLimiter(fake_counts({}), per_user=1, global_limit=100)
    with lim.reserve("a"):
        with pytest.raises(RateLimitExceeded):
            with lim.reserve("a"):            # second parallel request is refused
                pass
    with lim.reserve("a"):                    # released afterwards (nothing was logged in the fake)
        pass


# ---------- API ----------
class FakeAudit:
    def __init__(self):
        self.counts: dict[str, int] = {}

    def count_today(self, u=None):
        return sum(self.counts.values()) if u is None else self.counts.get(u, 0)

    def recent(self, n):
        return [{"id": 1, "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc), "username": "alice",
                 "question": "q", "final_sql": "select 1", "status": "ok", "row_count": 1, "latency_ms": 5}]


class FakePipeline:
    def __init__(self):
        self.audit, self.asked = FakeAudit(), []

    def ask(self, question, username=None):
        self.asked.append((question, username))
        self.audit.counts[username] = self.audit.counts.get(username, 0) + 1   # like the real audit write
        return Answer(question=question, status="ok", sql="SELECT 1", attempts=1, summary="One.",
                      result=QueryResult(columns=["x"], rows=[[1]], truncated=False))


def make_client(**overrides):
    cfg = Settings(openai_api_key="x", readonly_password="x", audit_password="x",
                   app_password="pw", auth_secret="secret", daily_limit_per_user=2,
                   daily_limit_global=100, _env_file=None, **overrides)
    pipe = FakePipeline()
    return TestClient(create_app(pipe, cfg)), pipe


def login(c, user="alice", pw="pw"):
    return c.post("/login", json={"username": user, "password": pw})


def auth(c, user="alice"):
    return {"Authorization": f"Bearer {login(c, user).json()['token']}"}


def test_health_needs_no_auth():
    with make_client()[0] as c:
        assert c.get("/health").status_code == 200


def test_login_ok_and_bad_password_and_bad_username():
    with make_client()[0] as c:
        r = login(c)
        assert r.status_code == 200 and r.json()["remaining_today"] == 2
        assert login(c, pw="nope").status_code == 401
        assert login(c, user="bad name!").status_code == 401
        assert login(c, user="a").status_code == 401           # too short


def test_allowed_users_list():
    with make_client(allowed_users="alice, bob")[0] as c:
        assert login(c, "alice").status_code == 200
        assert login(c, "mallory").status_code == 401


def test_ask_requires_valid_token():
    with make_client()[0] as c:
        assert c.post("/ask", json={"question": "how many orders?"}).status_code == 401
        assert c.post("/ask", json={"question": "how many orders?"},
                      headers={"Authorization": "Bearer junk"}).status_code == 401


def test_ask_returns_result_and_uses_token_username():
    c, pipe = make_client()
    with c:
        r = c.post("/ask", json={"question": "how many orders?"}, headers=auth(c, "Alice"))
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok" and body["rows"] == [[1]] and body["summary"] == "One."
        assert body["remaining_today"] == 1
        assert pipe.asked == [("how many orders?", "alice")]   # normalized, taken from token not request


def test_daily_limit_returns_429():
    c, _ = make_client()
    with c:
        h = auth(c)
        assert c.post("/ask", json={"question": "question one"}, headers=h).status_code == 200
        assert c.post("/ask", json={"question": "question two"}, headers=h).status_code == 200
        r = c.post("/ask", json={"question": "question three"}, headers=h)
        assert r.status_code == 429 and "questions for today" in r.json()["detail"]
        # another user still has quota
        assert c.post("/ask", json={"question": "question one"}, headers=auth(c, "bob")).status_code == 200


def test_long_and_short_questions_rejected():
    with make_client()[0] as c:
        h = auth(c)
        assert c.post("/ask", json={"question": "x" * 501}, headers=h).status_code == 422
        assert c.post("/ask", json={"question": "hi"}, headers=h).status_code == 422


def test_login_lockout_after_repeated_failures():
    with make_client()[0] as c:
        for _ in range(5):
            assert login(c, pw="wrong").status_code == 401
        assert login(c, pw="wrong").status_code == 429
        assert login(c).status_code == 429                      # even the right password is blocked


def test_history_and_usage():
    with make_client()[0] as c:
        h = auth(c)
        assert c.get("/history", headers=h).json()[0]["question"] == "q"
        assert c.get("/usage", headers=h).json()["remaining_today"] == 2
        assert c.get("/history").status_code == 401
