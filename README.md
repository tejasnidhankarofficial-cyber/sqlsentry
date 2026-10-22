# sqlsentry

A guarded text-to-SQL assistant. Ask data questions in plain English and get back the **SQL, the result table, and a short summary**, with guardrails that make it safe to point an LLM at a database.

Built on the [Olist Brazilian e-commerce dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) (~100k orders, 8 tables) with FastAPI, PostgreSQL, SQLAlchemy, OpenAI and Streamlit.

```
Question
  └─ LLM + schema card ──> SQL
        └─ SQL guard (parse, SELECT-only, table allowlist, LIMIT)
              └─ execute as a read-only role (timeout, row cap)
                    ├─ on error: feed the error back to the LLM, retry (max 2)
                    └─ summarize a capped sample of rows
                          └─ audit log ──> SQL + table + summary
```

## Why the LLM is only a translator

The model never sees or computes over your data. It turns a question into SQL, and Postgres produces the numbers. Every answer is therefore checkable (the SQL is shown), exact (counts and sums are computed by the database), and auditable. It describes what happened; it does not predict. For "will this customer churn?" you still need a model.

## Safety model: independent layers

| Layer | What it does | Where |
|---|---|---|
| **SQL guard** | Parses with `sqlglot`. Allows exactly one `SELECT`/`UNION`/CTE query. Rejects writes, DDL, `SELECT INTO`, `FOR UPDATE`, stacked statements, schema-qualified tables, dangerous functions (`pg_sleep`, `pg_read_file`, `set_config`, ...), and blocked columns. Caps `LIMIT`. | [app/sql_guard.py](app/sql_guard.py) |
| **Read-only DB role** | The query role has `SELECT` on 8 tables only, no access to review comments (column-level grant) or the audit schema, `default_transaction_read_only=on`, and a 5s `statement_timeout`. It does not trust the guard. | [db/init/03_roles.sh](db/init/03_roles.sh) |
| **Separate audit role** | Can only `INSERT`/`SELECT` on `audit.query_log`. It cannot update or delete history. | [db/init/03_roles.sh](db/init/03_roles.sh) |
| **Summary sees a sample** | Only the first 20 rows reach the LLM for summarization, not the full result. | [app/summarize.py](app/summarize.py) |
| **Access control** | Shared-password login, signed expiring tokens, login lockout, per-user daily quota, and a global daily cap. | [app/auth.py](app/auth.py), [app/ratelimit.py](app/ratelimit.py) |
| **Prompt-injection stance** | The question and the data are treated as untrusted. Safety never depends on the model behaving: the guard and the DB role hold even if it is fooled. | |

The guard has 70 adversarial tests ([tests/test_sql_guard.py](tests/test_sql_guard.py)), and the DB-role limits were verified against a live database.

## Quick start

Requirements: Docker, Python 3.11+, an OpenAI API key.

```bash
git clone https://github.com/tejasnidhankarofficial-cyber/sqlsentry.git && cd sqlsentry

# 1. Configure
cp .env.example .env          # then edit: OPENAI_API_KEY, APP_PASSWORD, AUTH_SECRET, DB passwords
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # use for AUTH_SECRET

# 2. Get the data (Kaggle login required; the CSVs are not in this repo)
#    https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
#    Unzip into ./data  (geolocation CSV is not used and may be deleted)

# 3. Start Postgres and load the data
make db && make load

# 4. Start everything
make up                       # API on :8000, UI on :8501
```

Open <http://127.0.0.1:8501>, log in with any name plus `APP_PASSWORD`. To run without Docker: `make setup`, then `uvicorn app.main:app` and `streamlit run ui/streamlit_app.py`.

Try: *"What are the top 5 product categories by revenue?"*, *"Which 3 states have the slowest delivery?"*, *"What percentage of delivered orders arrived late?"*

### API

| Endpoint | Purpose |
|---|---|
| `POST /login` | `{username, password}` -> bearer token |
| `POST /ask` | `{question}` -> `{status, sql, columns, rows, summary, remaining_today, ...}` |
| `GET /history` | Recent questions across the team |
| `GET /usage` | Your remaining daily quota |
| `GET /health` | Liveness |

`status` is one of `ok`, `cannot_answer`, `blocked`, `error`. Over-quota requests get HTTP 429.

## Schema-aware prompting

[db/schema_card.yaml](db/schema_card.yaml) is the single source of truth. It feeds the prompt (tables, columns, joins, business glossary, data quirks, query rules) **and** the guard's table allowlist. Most of the accuracy comes from this file, not the model. Examples of what it encodes:

- **"Customer"** means `COUNT(DISTINCT customer_unique_id)`. `customer_id` is per order (96,096 people vs 99,441 ids).
- **"Revenue"** means `SUM(price)` over delivered orders, excluding freight unless asked.
- **Fan-out rule:** aggregate `order_items` and `order_payments` separately before joining. Joining both to `orders` inflates revenue by ~4.5% (13.81M vs 13.22M).
- **Data quirks:** 13 categories have no English translation, 610 products have no category, ~550 orders have several reviews.

To point the system at another domain, replace this file and the seed data.

## Evaluation

[eval/golden_queries.yaml](eval/golden_queries.yaml) holds 30 tuned-on questions, 10 holdout questions written after the first baseline run, and 8 questions that must be refused. Each answerable question has hand-written reference SQL. A generated query passes if executing it returns the same rows as the reference (extra or renamed columns allowed, floats within tolerance). This is *execution accuracy*, not string matching.

Results with `gpt-4o-mini`, three full runs (`make eval`):

| | Result |
|---|---|
| Answerable questions (40) | **90-92%** (36-37 correct) |
| Tuned-on set (30) | 90-97% |
| Holdout set (10) | 80-90% |
| Refusals (8): injection, DROP, predictions, off-topic, review text | **100%** in every run |
| First baseline, before any prompt changes | 27/30 (90%) |

What this does and does not show:

- Output varies between runs even at `temperature=0`, so single-run numbers are noisy. The holdout set is only 10 questions; treat the gap between sets as indicative, not proven.
- Prompt changes after the baseline fixed one failure consistently (counting groups that satisfy a `HAVING` condition). A rule against adding unrequested filters did **not** reliably fix its target case.
- **Persistent failures:** a false refusal on a month-over-month growth question ("no data for November 2017", which exists); counting distinct English category names instead of falling back to the Portuguese name for untranslated categories; occasionally adding an unrequested filter to a delivery-time count; and sometimes omitting the delivered-orders filter on revenue.
- **Grader limits:** one case (`h08`) is graded on numeric values only, because the model's labels (`late`/`on_time`) and the reference's (`true`/`false`) have no canonical spelling. `YYYY-MM` is treated as equal to the first of that month. Both are in [eval/compare.py](eval/compare.py).
- The reference answers are mine and could contain mistakes on ambiguous questions.

## Design decisions and trade-offs

- **AST parsing over keyword blocklists.** A regex for `DROP|UPDATE|DELETE` is bypassed by CTE-wrapped writes, comments and stacked statements. Parsing sees the structure. A parser can still miss things, so the DB role is the real backstop.
- **Self-repair over failing.** DB errors go back to the model (up to 2 retries). This fixed type errors like `round(interval, integer)` on its own, at the cost of extra latency and tokens. All attempts are logged.
- **Structured refusal.** The model returns `can_answer=false` rather than inventing columns. This costs some false refusals (see above).
- **Quota counted from the audit log.** Limits survive restarts and need no extra infrastructure. The in-flight tracking that stops parallel requests slipping past the limit is per process, so with several server workers a user could slightly exceed it.
- **Whole schema in the prompt.** Fine for 8 tables. For hundreds of tables you would add retrieval to select relevant tables first.
- **Tokens, not sessions.** Stateless signed tokens keep the API simple; they cannot be revoked individually before expiry.

## Limitations

- Shared password plus self-chosen usernames: someone with the password can pick a new name to get a fresh per-user quota. The global daily cap bounds total spend; set `ALLOWED_USERS` for real per-person limits.
- Login lockout is per IP and in-memory (resets on restart; behind a proxy all users may share one IP).
- No conversation memory: each question is independent, so follow-ups like "and by state?" do not work yet.
- `SELECT *` on `order_reviews` is rejected by Postgres (comment columns are not granted) and relies on the repair loop.
- Descriptive only: no forecasting or causal analysis.
- Results are capped at 1,000 rows; the UI says when that happens.

## Deployment notes

- `docker-compose.yml` runs Postgres, API and UI; ports bind to `127.0.0.1`. To host it, put a TLS-terminating reverse proxy in front (Caddy, nginx, or a managed platform) and keep Postgres unexposed.
- Change every password in `.env` and use a fresh `AUTH_SECRET`. The `.env.example` values are placeholders.
- Set an OpenAI spend limit on the key. The global daily cap (`DAILY_LIMIT_GLOBAL`) is the second line of defence.
- Free hosting tiers sleep when idle; the first request can take a while.
- Before pushing to a public repo, run `make secrets-check`.

## Project structure

```
app/
  main.py          FastAPI endpoints
  pipeline.py      generate -> guard -> execute -> repair loop, summary, audit
  generate_sql.py  prompt + OpenAI structured output
  sql_guard.py     AST-based SQL validation
  execute.py       read-only execution with timeout and row cap
  summarize.py     summary from a capped sample
  audit.py         append-only audit log, daily counts
  auth.py          password check, signed tokens, login throttle
  ratelimit.py     per-user and global daily limits
  schema_card.py   loads and renders the schema card
  config.py        settings from environment
ui/streamlit_app.py
db/
  init/            schema, audit schema, roles (run on first container start)
  schema_card.yaml
eval/              golden queries, comparator, runner
scripts/           data loader, secrets check, manual question runner
tests/             guard, API, rate limit, UI and comparator tests
```

Run the tests with `make test` (97 tests, no OpenAI calls).

## Possible improvements

- Few-shot examples drawn from the golden query pairs
- Table retrieval for large schemas
- Join suggestions from foreign keys
- Per-user table and column access (RBAC)
- Conversation memory for follow-up questions
- Charts for numeric results

## Data and license

Code: MIT, see [LICENSE](LICENSE). Data: Olist Brazilian E-Commerce Public Dataset, released under CC BY-NC-SA 4.0 (attribution, non-commercial, share-alike). The CSVs are not redistributed here; download them from Kaggle.
