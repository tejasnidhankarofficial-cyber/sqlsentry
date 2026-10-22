"""Validates LLM-generated SQL before it touches the database.

First layer of defence: parse with sqlglot, allow exactly one read-only query over
allowlisted tables, and bound the row count. The read-only Postgres role
(db/init/03_roles.sh) is the second layer and does not trust this one.
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

MAX_SQL_CHARS = 5000

# Columns that exist in the table but must never be queried.
DEFAULT_BLOCKED_COLUMNS = frozenset({"review_comment_title", "review_comment_message"})

# Function-name prefixes / names that read files, sleep, change settings or reach other hosts.
_BLOCKED_FUNC_PREFIXES = ("pg_", "lo_", "dblink", "query_to_", "table_to_", "schema_to_",
                          "database_to_", "cursor_to_", "xpath")
_BLOCKED_FUNCS = frozenset({"set_config", "current_setting", "txid_current", "version",
                            "current_user", "session_user", "current_database", "current_version",
                            "current_schema", "current_schemas", "current_catalog",
                            "inet_server_addr", "inet_client_addr", "generate_series"})

# Node types that can never appear anywhere in the tree.
_FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter,
    exp.Command, exp.Set, exp.Copy, exp.TruncateTable, exp.Grant, exp.Transaction,
    exp.Commit, exp.Rollback, exp.Use, exp.Into, exp.Lock, exp.Pragma, exp.Describe,
)


class SQLGuardError(ValueError):
    """Raised when SQL is rejected. `code` is a stable machine-readable reason."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class GuardResult:
    sql: str                  # normalized SQL, safe to execute
    tables: frozenset[str]    # real tables referenced
    limit_applied: bool       # True if we added or lowered a LIMIT


def validate_sql(
    sql: str,
    allowed_tables: set[str] | frozenset[str],
    max_rows: int = 1000,
    blocked_columns: frozenset[str] = DEFAULT_BLOCKED_COLUMNS,
) -> GuardResult:
    if not sql or not sql.strip():
        raise SQLGuardError("empty", "Empty SQL.")
    if len(sql) > MAX_SQL_CHARS:
        raise SQLGuardError("too_long", f"SQL longer than {MAX_SQL_CHARS} characters.")

    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except SqlglotError as e:
        raise SQLGuardError("parse_error", f"Could not parse SQL: {e}") from e

    if len(statements) != 1:
        raise SQLGuardError("multiple_statements", "Exactly one statement is allowed.")
    root = statements[0]

    if not isinstance(root, (exp.Select, exp.SetOperation)):
        raise SQLGuardError("not_select", "Only SELECT queries are allowed.")

    allowed = {t.lower() for t in allowed_tables}
    cte_names = {c.alias_or_name.lower() for c in root.find_all(exp.CTE)}
    tables: set[str] = set()

    for node in root.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SQLGuardError("forbidden_statement",
                                f"{type(node).__name__} is not allowed in a read-only query.")

        if isinstance(node, exp.Table):
            if not isinstance(node.this, exp.Identifier):
                raise SQLGuardError("forbidden_function", "Table-valued functions are not allowed.")
            name = node.name.lower()
            if node.args.get("db") or node.args.get("catalog"):
                raise SQLGuardError("schema_qualified",
                                    f"Schema-qualified table '{node.db}.{node.name}' is not allowed.")
            if name in cte_names:
                continue
            if name not in allowed:
                raise SQLGuardError("table_not_allowed", f"Table '{node.name}' is not allowed.")
            tables.add(name)

        elif isinstance(node, exp.Func):
            fname = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if fname in _BLOCKED_FUNCS or fname.startswith(_BLOCKED_FUNC_PREFIXES):
                raise SQLGuardError("forbidden_function", f"Function '{fname}' is not allowed.")

        elif isinstance(node, exp.Column) and node.name.lower() in blocked_columns:
            raise SQLGuardError("column_not_allowed", f"Column '{node.name}' is not available.")

    limit_applied = False
    limit = root.args.get("limit")
    if limit is None:
        root = root.limit(max_rows)
        limit_applied = True
    else:
        expr = limit.expression
        if isinstance(expr, exp.Literal) and expr.is_int:
            if int(expr.this) > max_rows:
                root = root.limit(max_rows)
                limit_applied = True
        else:  # LIMIT ALL, LIMIT NULL, LIMIT (subquery) ...
            root = root.limit(max_rows)
            limit_applied = True

    return GuardResult(sql=root.sql(dialect="postgres"), tables=frozenset(tables),
                       limit_applied=limit_applied)
