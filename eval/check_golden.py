"""Runs every reference SQL against the DB and prints its result, so a human can sanity-check them."""
import yaml

from app.config import ROOT, get_settings
from app.execute import Executor

cases = yaml.safe_load((ROOT / "eval" / "golden_queries.yaml").read_text())["cases"]
ex = Executor(get_settings())
for c in cases:
    r = ex.run(c["sql"])
    print(f"{c['id']} [{c['level']}] {c['question'][:70]}\n     -> {r.rows[:5]}{' ...' if len(r.rows) > 5 else ''}")
