"""question -> SQL -> guard -> execute, with a bounded self-repair loop."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from app.audit import AuditEntry, AuditLogger
from app.config import Settings, get_settings
from app.execute import ExecutionError, Executor, QueryResult
from app.generate_sql import SQLGenerator
from app.schema_card import allowed_tables, load_card
from app.sql_guard import SQLGuardError, validate_sql
from app.summarize import Summarizer

log = logging.getLogger(__name__)


@dataclass
class Answer:
    question: str
    status: str                       # ok | cannot_answer | blocked | error
    sql: str | None = None            # last SQL attempted (normalized if it passed the guard)
    result: QueryResult | None = None
    message: str | None = None        # reason / error shown to the user
    summary: str | None = None        # natural-language summary of the result
    latency_ms: int = 0
    attempts: int = 0
    trace: list[dict] = field(default_factory=list)  # one entry per attempt, for audit


class Pipeline:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        card = load_card(self.settings.schema_card_path)
        self.allowed = allowed_tables(card)
        self.generator = SQLGenerator(self.settings, card)
        self.executor = Executor(self.settings)
        self.summarizer = Summarizer(self.settings)
        self.audit = AuditLogger(self.settings)

    def ask(self, question: str, username: str | None = None) -> Answer:
        start = time.monotonic()
        ans = self.run_query(question)

        if ans.status == "ok" and ans.result is not None:
            try:
                ans.summary = self.summarizer.summarize(question, ans.result)
            except Exception:  # the table is still useful without a summary
                log.exception("summarization failed")

        ans.latency_ms = int((time.monotonic() - start) * 1000)
        first_sql = next((t.get("sql") for t in ans.trace if t.get("sql")), None)
        self.audit.record(AuditEntry(
            username=username, question=question, generated_sql=first_sql,
            final_sql=ans.sql, status=ans.status,
            error=None if ans.status == "ok" else ans.message,
            attempts=ans.attempts,
            row_count=len(ans.result.rows) if ans.result else None,
            latency_ms=ans.latency_ms,
        ))
        return ans

    def run_query(self, question: str) -> Answer:
        """Generate, guard, execute and repair. No summary and no audit entry."""
        ans = Answer(question=question, status="error")
        failures: list[tuple[str, str]] = []

        for attempt in range(1, self.settings.max_repairs + 2):
            ans.attempts = attempt
            draft = self.generator.generate(question, failures)

            if not draft.can_answer or not draft.sql:
                ans.status, ans.message = "cannot_answer", draft.reason or "Cannot answer from this database."
                ans.trace.append({"attempt": attempt, "outcome": "cannot_answer", "detail": ans.message})
                return ans

            ans.sql = draft.sql
            try:
                guarded = validate_sql(draft.sql, self.allowed, max_rows=self.settings.max_rows)
                ans.sql = guarded.sql
                ans.result = self.executor.run(guarded.sql)
            except SQLGuardError as e:
                error, outcome = e.message, f"blocked:{e.code}"
            except ExecutionError as e:
                error, outcome = e.message, e.code
            else:
                ans.status = "ok"
                ans.trace.append({"attempt": attempt, "outcome": "ok", "sql": ans.sql})
                return ans

            ans.trace.append({"attempt": attempt, "outcome": outcome, "sql": draft.sql, "detail": error})
            ans.message = error
            ans.status = "blocked" if outcome.startswith("blocked") else "error"
            failures.append((draft.sql, error))

        return ans
