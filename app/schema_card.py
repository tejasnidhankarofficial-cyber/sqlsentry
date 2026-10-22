"""Loads db/schema_card.yaml and renders it as prompt text."""
from functools import lru_cache
from pathlib import Path

import yaml


@lru_cache
def load_card(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def allowed_tables(card: dict) -> frozenset[str]:
    return frozenset(card["tables"])


def render_schema(card: dict) -> str:
    out = [f"Database: PostgreSQL. {card['description'].strip()}", "", "TABLES"]
    for name, t in card["tables"].items():
        out.append(f"- {name}: {t['description']}")
        for col, desc in t["columns"].items():
            out.append(f"    {col}: {desc}")
    out += ["", "JOINS"] + [f"- {r}" for r in card["relationships"]]
    out += ["", "BUSINESS DEFINITIONS (follow these exactly)"]
    out += [f"- {g['term']}: {g['rule'].strip()}" for g in card["glossary"]]
    out += ["", "DATA QUIRKS"] + [f"- {q}" for q in card.get("data_quirks", [])]
    out += ["", "QUERY RULES"] + [f"- {r}" for r in card["query_rules"]]
    return "\n".join(out)
