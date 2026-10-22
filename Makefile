.PHONY: run stop restart status logs clean setup db load test eval secrets-check help
help:             ## list commands
	@grep -E '^[a-z-]+:.*##' Makefile | sed 's/:.*##/ -/'

run:              ## start everything (db, API, UI); loads data on first run
	./scripts/run.sh
stop:             ## stop and remove the containers (data volume is kept)
	docker compose down
restart: stop run ## stop, then start again
status:           ## show container status
	docker compose ps
logs:             ## follow logs from all containers
	docker compose logs -f
clean:            ## stop AND delete the database volume (reload data on next run)
	docker compose down -v

setup:            ## create venv and install dev dependencies
	python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
db:               ## start Postgres only
	docker compose up -d --wait db
load:             ## load Olist CSVs from ./data into Postgres
	./scripts/load_data.sh
test:
	.venv/bin/python -m pytest tests -q
eval:             ## execution-accuracy evaluation (calls the OpenAI API)
	.venv/bin/python -m eval.run_eval
secrets-check:    ## run before pushing
	python3 scripts/check_secrets.py
