-- Audit log lives in its own schema, invisible to the read-only query role.
CREATE SCHEMA audit;

CREATE TABLE audit.query_log (
    id            bigserial PRIMARY KEY,
    created_at    timestamptz NOT NULL DEFAULT now(),
    username      text,
    question      text NOT NULL,
    generated_sql text,
    final_sql     text,
    status        text NOT NULL,   -- ok | blocked | error | cannot_answer
    error         text,
    attempts      integer NOT NULL DEFAULT 1,
    row_count     integer,
    latency_ms    integer
);
