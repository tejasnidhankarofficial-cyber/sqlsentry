"""Append-only audit log of every question, as the olist_audit role."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import create_engine, text

from app.config import Settings

log = logging.getLogger(__name__)

_INSERT = text("""
    INSERT INTO audit.query_log
        (username, question, generated_sql, final_sql, status, error, attempts, row_count, latency_ms)
    VALUES (:username, :question, :generated_sql, :final_sql, :status, :error, :attempts, :row_count, :latency_ms)
""")

_RECENT = text("""
    SELECT id, created_at, username, question, final_sql, status, row_count, latency_ms
    FROM audit.query_log ORDER BY id DESC LIMIT :n
""")


_COUNT_TODAY = text("""
    SELECT count(*) FROM audit.query_log
    WHERE created_at >= date_trunc('day', now() AT TIME ZONE 'utc') AT TIME ZONE 'utc'
      AND (CAST(:username AS text) IS NULL OR username = :username)
""")


@dataclass
class AuditEntry:
    username: str | None
    question: str
    generated_sql: str | None
    final_sql: str | None
    status: str
    error: str | None
    attempts: int
    row_count: int | None
    latency_ms: int


class AuditLogger:
    def __init__(self, settings: Settings):
        self.engine = create_engine(settings.db_url("olist_audit", settings.audit_password),
                                    pool_pre_ping=True)

    def record(self, e: AuditEntry) -> None:
        """Never raises: an audit outage is logged loudly but must not take the app down."""
        try:
            with self.engine.begin() as conn:
                conn.execute(_INSERT, e.__dict__)
        except Exception:
            log.exception("AUDIT WRITE FAILED for question=%r", e.question[:200])

    def recent(self, n: int = 20) -> list[dict]:
        with self.engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(_RECENT, {"n": n})]

    def count_today(self, username: str | None = None) -> int:
        """Questions logged since 00:00 UTC, for one user or (username=None) everyone."""
        with self.engine.connect() as conn:
            return conn.execute(_COUNT_TODAY, {"username": username}).scalar_one()
