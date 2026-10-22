"""Quick manual check: python -m scripts.try_question "your question" ..."""
import sys

from app.pipeline import Pipeline

p = Pipeline()
for q in sys.argv[1:]:
    a = p.ask(q, username="cli")
    print(f"\nQ: {q}\n  status={a.status} attempts={a.attempts} latency={a.latency_ms}ms")
    if a.sql:
        print("  SQL:", " ".join(a.sql.split()))
    if a.result:
        print(f"  cols={a.result.columns} rows={len(a.result.rows)} first={a.result.rows[:3]}")
    if a.summary:
        print("  SUMMARY:", a.summary)
    if a.status != "ok":
        print("  message:", a.message)
