"""Execution-accuracy comparison of two result sets."""
from __future__ import annotations

import itertools
import math
import re
from typing import Any

_MIDNIGHT = re.compile(r"^(\d{4}-\d{2}-\d{2})T00:00:00$")
_YEAR_MONTH = re.compile(r"^(\d{4}-\d{2})$")
MAX_GEN_COLS_FOR_SEARCH = 7


def _norm(v: Any) -> Any:
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = _MIDNIGHT.match(v)
        if m:
            return m.group(1)
        m = _YEAR_MONTH.match(v)
        return f"{m.group(1)}-01" if m else v
    return str(v)


def _key(row: tuple) -> tuple:
    return tuple((0, round(v, 1)) if isinstance(v, float) and not isinstance(v, bool)
                 else (1, str(v)) for v in row)


def _close(a: Any, b: Any) -> bool:
    if isinstance(a, float) and isinstance(b, float) and not isinstance(a, bool):
        return math.isclose(a, b, rel_tol=1e-3, abs_tol=0.011)
    return a == b


def _rows_match(ref: list[tuple], got: list[tuple], ordered: bool) -> bool:
    if len(ref) != len(got):
        return False
    if not ordered:
        ref, got = sorted(ref, key=_key), sorted(got, key=_key)
    return all(len(r) == len(g) and all(_close(x, y) for x, y in zip(r, g)) for r, g in zip(ref, got))


def _numeric_columns(rows: list[list]) -> list[list]:
    """Keep only columns whose values are all numbers (drops labels such as 'late' vs True)."""
    if not rows:
        return rows
    keep = [i for i in range(len(rows[0]))
            if all(isinstance(r[i], (int, float)) and not isinstance(r[i], bool) for r in rows)]
    return [[r[i] for i in keep] for r in rows]


def results_match(ref_rows: list[list], got_rows: list[list], ordered: bool,
                  numeric_only: bool = False) -> tuple[bool, str]:
    """True if some projection of the generated columns equals the reference rows.

    Extra columns and different column names/order are tolerated; wrong values or row counts are not.
    """
    if numeric_only:  # for questions whose group labels have no single canonical spelling
        ref_rows, got_rows = _numeric_columns(ref_rows), _numeric_columns(got_rows)
    ref = [tuple(_norm(v) for v in r) for r in ref_rows]
    got = [tuple(_norm(v) for v in r) for r in got_rows]
    k = len(ref[0]) if ref else 0
    m = len(got[0]) if got else k

    if not ref and not got:
        return True, "both empty"
    if len(ref) != len(got):
        return False, f"row count {len(got)} != expected {len(ref)}"
    if m < k:
        return False, f"{m} column(s) returned, expected at least {k}"

    candidates = (itertools.permutations(range(m), k) if m <= MAX_GEN_COLS_FOR_SEARCH
                  else [tuple(range(k))])
    for cols in candidates:
        if _rows_match(ref, [tuple(r[i] for i in cols) for r in got], ordered):
            return True, "match" if m == k else f"match (+{m - k} extra column(s))"
    return False, f"values differ: got {got[:3]} expected {ref[:3]}"
