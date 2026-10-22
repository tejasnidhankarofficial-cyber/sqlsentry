.PHONY: setup db load up down test eval secrets-check
setup:            ## create venv and install dependencies
	python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
db:               ## start Postgres only
	docker compose up -d db
load:             ## load Olist CSVs from ./data into Postgres
	./scripts/load_data.sh
up:               ## start Postgres, API (:8000) and UI (:8501)
	docker compose up -d --build
down:
	docker compose down
test:
	.venv/bin/python -m pytest tests -q
eval:             ## execution-accuracy evaluation (calls the OpenAI API)
	.venv/bin/python -m eval.run_eval
secrets-check:    ## run before pushing
	python3 scripts/check_secrets.py
