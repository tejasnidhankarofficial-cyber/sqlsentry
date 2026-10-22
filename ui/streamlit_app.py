"""Streamlit front end. Talks only to the FastAPI service; holds no keys or DB access."""
import os

import httpx
import pandas as pd
import streamlit as st

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 60  # generation + execution + summary can take several seconds

EXAMPLES = [
    "How many unique customers do we have?",
    "What are the top 5 product categories by revenue?",
    "Which 3 states have the slowest average delivery time?",
    "How many orders were placed each month in 2017?",
    "What share of payments is by credit card?",
]
STATUS_ICON = {"ok": "✅", "cannot_answer": "🤷", "blocked": "🛑", "error": "⚠️"}

st.set_page_config(page_title="SQL QnA Assistant", page_icon="🗄️", layout="centered")


def api(method: str, path: str, **kwargs):
    """Returns (response, error_message). Logs the user out when the token is rejected."""
    headers = {"Authorization": f"Bearer {st.session_state['token']}"} if "token" in st.session_state else {}
    try:
        r = httpx.request(method, f"{API_URL}{path}", headers=headers, timeout=TIMEOUT, **kwargs)
    except httpx.HTTPError:
        return None, f"Cannot reach the API at {API_URL}. Is it running?"
    if r.status_code == 401 and "token" in st.session_state:
        logout()
        return None, "Your session expired. Please log in again."
    return r, None


def logout():
    for k in ("token", "username", "remaining", "limit", "result"):
        st.session_state.pop(k, None)


def login_view():
    st.title("🗄️ SQL QnA Assistant")
    st.caption("Ask questions about the Olist e-commerce data in plain English.")
    with st.form("login"):
        username = st.text_input("Your name", placeholder="e.g. tejas")
        password = st.text_input("Team password", type="password")
        if st.form_submit_button("Log in", width="stretch"):
            r, err = api("POST", "/login", json={"username": username, "password": password})
            if err:
                st.error(err)
            elif r.status_code == 200:
                d = r.json()
                st.session_state.update(token=d["token"], username=d["username"],
                                        remaining=d["remaining_today"], limit=d["daily_limit"])
                st.rerun()
            else:
                st.error(r.json().get("detail", "Login failed."))


def show_result(res: dict):
    icon = STATUS_ICON.get(res["status"], "")
    if res["status"] == "ok":
        if res.get("summary"):
            st.success(res["summary"])
        df = pd.DataFrame(res["rows"], columns=res["columns"])
        st.dataframe(df, width="stretch", hide_index=True)
        note = f"{res['row_count']} row(s)"
        if res.get("truncated"):
            note += f" — capped at the row limit; more rows exist"
        st.caption(f"{note} · {res['latency_ms'] / 1000:.1f}s"
                   + (f" · fixed after {res['attempts'] - 1} retry" if res["attempts"] > 1 else ""))
        st.download_button("Download CSV", df.to_csv(index=False), "result.csv", "text/csv")
    elif res["status"] == "cannot_answer":
        st.info(f"{icon} I can't answer that from this database: {res.get('message', '')}")
    elif res["status"] == "blocked":
        st.error(f"{icon} The generated query was blocked by the safety checks: {res.get('message', '')}")
    else:
        st.error(f"{icon} The query failed after {res['attempts']} attempts: {res.get('message', '')}")
    if res.get("sql"):
        with st.expander("Show SQL"):
            st.code(res["sql"], language="sql")


def sidebar():
    with st.sidebar:
        st.markdown(f"**{st.session_state['username']}**")
        st.metric("Questions left today", f"{st.session_state['remaining']} / {st.session_state['limit']}")
        if st.button("Log out", width="stretch"):
            logout()
            st.rerun()
        st.divider()
        st.subheader("Recent team questions")
        r, _ = api("GET", "/history", params={"limit": 10})
        if r is not None and r.status_code == 200:
            for h in r.json():
                st.caption(f"{STATUS_ICON.get(h['status'], '')} **{h['username'] or '?'}**: {h['question']}")


def ask_view():
    sidebar()
    st.title("🗄️ SQL QnA Assistant")

    def use_example(q):
        st.session_state["question"] = q

    question = st.text_area("Your question", key="question", height=90, max_chars=500,
                            placeholder="e.g. Which sellers have an average review score below 3?")
    if st.button("Ask", type="primary", width="stretch", disabled=not question.strip()):
        with st.spinner("Writing and running the query..."):
            r, err = api("POST", "/ask", json={"question": question})
        if err:
            st.error(err)
        elif r.status_code == 200:
            st.session_state["result"] = r.json()
            st.session_state["remaining"] = r.json()["remaining_today"]
            st.rerun()
        elif r.status_code == 429:
            st.warning(r.json().get("detail", "Daily limit reached."))
        else:
            st.error(r.json().get("detail", f"Request failed ({r.status_code})."))

    if "result" in st.session_state:
        show_result(st.session_state["result"])
    else:
        st.caption("Try one of these:")
        for q in EXAMPLES:
            st.button(q, on_click=use_example, args=(q,), width="stretch")


if "token" in st.session_state:
    ask_view()
else:
    login_view()
