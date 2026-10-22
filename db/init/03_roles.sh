#!/bin/bash
# Creates the two application roles. Runs once, on first container start.
set -euo pipefail

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     -v ro_pw="$READONLY_PASSWORD" -v audit_pw="$AUDIT_PASSWORD" <<'SQL'

-- Query role: what LLM-generated SQL runs as. The real safety net behind the SQL guard.
CREATE ROLE olist_readonly LOGIN PASSWORD :'ro_pw'
    NOSUPERUSER NOCREATEDB NOCREATEROLE;
ALTER ROLE olist_readonly SET default_transaction_read_only = on;
ALTER ROLE olist_readonly SET statement_timeout = '5s';
ALTER ROLE olist_readonly SET idle_in_transaction_session_timeout = '10s';

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO olist_readonly;
GRANT SELECT ON customers, sellers, products, product_category_translation,
               orders, order_items, order_payments
    TO olist_readonly;
-- Column-level grant: free-text review comments are deliberately excluded.
GRANT SELECT (review_id, order_id, review_score,
              review_creation_date, review_answer_timestamp)
    ON order_reviews TO olist_readonly;

-- Audit role: can only append to the audit log.
CREATE ROLE olist_audit LOGIN PASSWORD :'audit_pw'
    NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT USAGE ON SCHEMA audit TO olist_audit;
GRANT INSERT, SELECT ON audit.query_log TO olist_audit;
GRANT USAGE ON SEQUENCE audit.query_log_id_seq TO olist_audit;
SQL
