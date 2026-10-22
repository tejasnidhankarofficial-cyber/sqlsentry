"""Pre-push check: fail if any real secret from .env appears in a file that would be committed.

Usage: python scripts/check_secrets.py
Skips what .gitignore skips. Values that also appear in .env.example are treated as placeholders.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "data", "pgdata", "__pycache__", ".pytest_cache", "results"}
SKIP_FILES = {".env"}
KEY_LIKE = re.compile(r"(PASSWORD|SECRET|KEY|TOKEN)", re.I)
GENERIC = re.compile(r"sk-[A-Za-z0-9_\-]{20,}")


def parse_env(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.split("#")[0].strip()
    return out


def main() -> int:
    env = parse_env(ROOT / ".env") if (ROOT / ".env").exists() else {}
    example = set(parse_env(ROOT / ".env.example").values()) if (ROOT / ".env.example").exists() else set()
    secrets = {v for k, v in env.items() if KEY_LIKE.search(k) and len(v) >= 6 and v not in example}

    hits = []
    for f in ROOT.rglob("*"):
        rel = f.relative_to(ROOT)
        if not f.is_file() or f.name in SKIP_FILES or SKIP_DIRS & set(rel.parts):
            continue
        try:
            text = f.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for s in secrets:
            if s in text:
                hits.append(f"{rel}: contains a value from .env")
        if GENERIC.search(text):
            hits.append(f"{rel}: looks like an API key")

    if hits:
        print("SECRETS FOUND - do not push:\n  " + "\n  ".join(sorted(set(hits))))
        return 1
    print(f"OK: no secrets found ({len(secrets)} secret values from .env checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
