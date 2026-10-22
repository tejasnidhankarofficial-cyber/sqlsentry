#!/bin/bash
# One-command start: builds and starts db + api + ui, waits until healthy, loads data if the DB is empty.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "No .env found. Run: cp .env.example .env   and fill in OPENAI_API_KEY, APP_PASSWORD, AUTH_SECRET" >&2
  exit 1
fi
set -a; source .env; set +a
if [[ "${OPENAI_API_KEY:-}" == "sk-..." || -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY in .env is not set." >&2
  exit 1
fi
docker info >/dev/null 2>&1 || { echo "Docker is not running. Start Docker Desktop and retry." >&2; exit 1; }

echo "Starting containers (first run builds the image)..."
docker compose up -d --build --wait db
rows=$(docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM orders" 2>/dev/null || echo 0)
if [[ "$rows" == "0" ]]; then
  if [[ -f data/olist_orders_dataset.csv ]]; then
    echo "Database is empty - loading the Olist data..."
    ./scripts/load_data.sh
  else
    echo "WARNING: database is empty and no CSVs found in ./data (see README, step 2). Questions will return nothing." >&2
  fi
fi
docker compose up -d --build --wait

cat <<MSG

sqlsentry is running
  UI : http://127.0.0.1:8501   (log in with any name + APP_PASSWORD from .env)
  API: http://127.0.0.1:8000/docs

Stop it with: make stop
MSG
