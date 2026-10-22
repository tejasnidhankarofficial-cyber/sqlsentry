"""Runs guarded SQL as the read-only role with a timeout and row cap."""
from __future__ import annotations

import datetime as dt
import decimal
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.config import Settings


class ExecutionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code        # "timeout" | "db_error"
        self.message = message


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool


def _jsonable(v: Any) -> Any:
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    return v


class Executor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine = create_engine(
            settings.db_url("olist_readonly", settings.readonly_password),
            pool_pre_ping=True,
            connect_args={"options": f"-c statement_timeout={settings.statement_timeout_ms} "
                                     f"-c default_transaction_read_only=on"},
        )

    def run(self, sql: str) -> QueryResult:
        cap = self.settings.max_rows
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(sql))
                columns = list(result.keys())
                fetched = result.fetchmany(cap + 1)
        except DBAPIError as e:
            msg = str(e.orig).strip().splitlines()[0] if e.orig else str(e)
            code = "timeout" if "statement timeout" in msg else "db_error"
            raise ExecutionError(code, msg) from e
        truncated = len(fetched) > cap
        rows = [[_jsonable(v) for v in r] for r in fetched[:cap]]
        return QueryResult(columns=columns, rows=rows, truncated=truncated)
