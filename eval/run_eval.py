"""Execution-accuracy evaluation.   python -m eval.run_eval [--ids e01 m02] [--workers 4]

Uses Pipeline.run_query, so no summaries are generated and nothing is written to the audit log.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import yaml

from app.config import ROOT, get_settings
from app.pipeline import Pipeline
from eval.compare import results_match

GOLDEN = ROOT / "eval" / "golden_queries.yaml"
OUT_DIR = ROOT / "eval" / "results"


def run_case(pipe: Pipeline, ref_exec, case: dict) -> dict:
    t0 = time.monotonic()
    ans = pipe.run_query(case["question"])
    rec = {"id": case["id"], "level": case.get("level", "refusal"), "question": case["question"],
           "holdout": bool(case.get("holdout")), "status": ans.status, "attempts": ans.attempts, "sql": ans.sql,
           "latency_s": round(time.monotonic() - t0, 1)}

    if "sql" not in case:                                    # refusal case: must not be answered
        rec["passed"] = ans.status != "ok"
        rec["detail"] = ans.message if rec["passed"] else "answered a question it should refuse"
        return rec

    if ans.status != "ok":
        rec["passed"], rec["detail"] = False, f"{ans.status}: {ans.message}"
        return rec
    expected = ref_exec.run(case["sql"])
    rec["passed"], rec["detail"] = results_match(expected.rows, ans.result.rows, case.get("ordered", False),
                                       case.get("numeric_only", False))
    return rec


def report(results: list[dict], model: str) -> str:
    lines = [f"# Evaluation results\n", f"Model: `{model}` · {len(results)} cases\n",
             "| Level | Passed | Total | Accuracy |", "|---|---|---|---|"]
    for level in ("easy", "medium", "hard", "refusal"):
        rs = [r for r in results if r["level"] == level]
        if rs:
            p = sum(r["passed"] for r in rs)
            lines.append(f"| {level} | {p} | {len(rs)} | {100 * p / len(rs):.0f}% |")
    answerable = [r for r in results if r["level"] != "refusal"]
    if answerable:
        p = sum(r["passed"] for r in answerable)
        lines.append(f"| **execution accuracy (answerable)** | {p} | {len(answerable)} | **{100 * p / len(answerable):.0f}%** |")
    for name, flag in (("tuned-on set", False), ("holdout set", True)):
        rs = [r for r in answerable if r["holdout"] == flag]
        if rs:
            p = sum(r["passed"] for r in rs)
            lines.append(f"| {name} | {p} | {len(rs)} | {100 * p / len(rs):.0f}% |")
    first_try = [r for r in answerable if r["passed"] and r["attempts"] == 1]
    repaired = [r for r in answerable if r["passed"] and r["attempts"] > 1]
    lat = [r["latency_s"] for r in results]
    lines += ["", f"- Passed on first attempt: {len(first_try)}, passed after self-repair: {len(repaired)}",
              f"- Median latency (SQL only, no summary): {statistics.median(lat):.1f}s"]
    failures = [r for r in results if not r["passed"]]
    if failures:
        lines += ["", "## Failures", ""]
        for r in failures:
            lines += [f"- **{r['id']}** ({r['level']}) {r['question']}", f"  - {r['detail']}",
                      f"  - SQL: `{' '.join((r['sql'] or '').split())[:300]}`"]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    spec = yaml.safe_load(GOLDEN.read_text())
    cases = spec["cases"] + spec["refusals"]
    if args.ids:
        cases = [c for c in cases if c["id"] in args.ids]

    settings = get_settings()
    pipe = Pipeline(settings)
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda c: run_case(pipe, pipe.executor, c), cases))

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "latest.json").write_text(json.dumps(results, indent=2, default=str))
    md = report(results, settings.openai_model)
    (OUT_DIR / "latest.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
