from pathlib import Path
from unittest.mock import patch

import httpx
from streamlit.testing.v1 import AppTest

UI = Path(__file__).resolve().parent.parent / "ui" / "streamlit_app.py"
LOGIN_OK = {"token": "t", "username": "alice", "daily_limit": 50, "remaining_today": 49}
ASK_OK = {"status": "ok", "question": "q", "sql": "SELECT 1", "columns": ["n"], "rows": [[7]],
          "row_count": 1, "truncated": False, "summary": "There are 7.", "message": None,
          "attempts": 1, "latency_ms": 1200, "remaining_today": 48}


def resp(code, body):
    return httpx.Response(code, json=body, request=httpx.Request("GET", "http://x"))


def fake_request(method, url, **kw):
    if url.endswith("/login"):
        ok = kw["json"]["password"] == "pw"
        return resp(200, LOGIN_OK) if ok else resp(401, {"detail": "Invalid username or password."})
    if url.endswith("/history"):
        return resp(200, [{"username": "bob", "status": "ok", "question": "earlier q"}])
    if url.endswith("/ask"):
        return resp(429, {"detail": "You have used all 50 questions for today."}) \
            if kw["json"]["question"] == "limit" else resp(200, ASK_OK)
    raise AssertionError(url)


def run():
    at = AppTest.from_file(str(UI), default_timeout=10)
    at.run()
    return at


def login(at, pw="pw"):
    at.text_input[0].set_value("alice")
    at.text_input[1].set_value(pw)
    at.button[0].click().run()


@patch("httpx.request", side_effect=fake_request)
def test_login_failure_shows_error(_):
    at = run()
    login(at, pw="bad")
    assert not at.exception and "Invalid username" in at.error[0].value


@patch("httpx.request", side_effect=fake_request)
def test_login_then_ask_shows_summary_table_and_sql(_):
    at = run()
    login(at)
    assert not at.exception and at.metric[0].value == "49 / 50"
    at.text_area[0].set_value("how many?").run()
    next(b for b in at.button if b.label == "Ask").click().run()
    assert not at.exception
    assert at.success[0].value == "There are 7."
    assert at.metric[0].value == "48 / 50"
    assert at.dataframe[0].value.iloc[0, 0] == 7


@patch("httpx.request", side_effect=fake_request)
def test_rate_limit_message(_):
    at = run()
    login(at)
    at.text_area[0].set_value("limit").run()
    next(b for b in at.button if b.label == "Ask").click().run()
    assert not at.exception and "50 questions" in at.warning[0].value


@patch("httpx.request", side_effect=httpx.ConnectError("down"))
def test_api_down_is_handled(_):
    at = run()
    login(at)
    assert not at.exception and "Cannot reach the API" in at.error[0].value
