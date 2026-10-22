import pytest

from app.sql_guard import SQLGuardError, validate_sql

ALLOWED = {"orders", "order_items", "order_payments", "order_reviews", "customers",
           "sellers", "products", "product_category_translation"}


def check(sql, **kw):
    return validate_sql(sql, ALLOWED, **kw)


# ---------- legitimate queries pass ----------
@pytest.mark.parametrize("sql", [
    "SELECT count(*) FROM orders",
    "SELECT o.order_id FROM orders o JOIN order_items i ON i.order_id = o.order_id",
    "WITH d AS (SELECT * FROM orders WHERE order_status = 'delivered') SELECT count(*) FROM d",
    "SELECT order_id FROM orders UNION SELECT order_id FROM order_items",
    "SELECT date_trunc('month', order_purchase_timestamp) m, count(*) FROM orders GROUP BY 1 ORDER BY 1",
    "SELECT * FROM orders WHERE order_id IN (SELECT order_id FROM order_items)",
    "select review_score, count(*) from order_reviews group by 1",
    "SELECT 1;",
    "SELECT 'DROP TABLE orders' AS note FROM orders",       # keyword inside a string literal
])
def test_valid_queries_pass(sql):
    assert check(sql).sql


# ---------- write / DDL / admin statements ----------
@pytest.mark.parametrize("sql", [
    "DROP TABLE orders",
    "DELETE FROM orders",
    "UPDATE orders SET order_status = 'x'",
    "INSERT INTO orders (order_id) VALUES ('a')",
    "TRUNCATE orders",
    "ALTER TABLE orders ADD COLUMN x int",
    "CREATE TABLE t AS SELECT * FROM orders",
    "GRANT ALL ON orders TO public",
    "COPY orders TO '/tmp/x'",
    "SET statement_timeout = 0",
    "EXPLAIN ANALYZE SELECT 1",
    "VACUUM",
    "BEGIN",
])
def test_non_select_rejected(sql):
    with pytest.raises(SQLGuardError):
        check(sql)


# ---------- smuggling writes inside a SELECT shape ----------
@pytest.mark.parametrize("sql", [
    "SELECT 1; DROP TABLE orders",
    "SELECT 1; SELECT 2",
    "WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x",
    "WITH x AS (UPDATE orders SET order_status='a' RETURNING *) SELECT * FROM x",
    "WITH x AS (INSERT INTO orders (order_id) VALUES ('a') RETURNING *) SELECT * FROM x",
    "SELECT * INTO new_table FROM orders",
    "SELECT * FROM orders FOR UPDATE",
])
def test_smuggled_writes_rejected(sql):
    with pytest.raises(SQLGuardError):
        check(sql)


# ---------- table allowlist ----------
@pytest.mark.parametrize("sql", [
    "SELECT * FROM pg_user",
    "SELECT * FROM pg_catalog.pg_tables",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM audit.query_log",
    "SELECT * FROM public.orders",
    "SELECT * FROM geolocation",
    "SELECT * FROM orders o JOIN secrets s ON true",
    "SELECT * FROM orders WHERE order_id IN (SELECT id FROM secrets)",
    "WITH x AS (SELECT * FROM secrets) SELECT * FROM x",
    "SELECT (SELECT count(*) FROM secrets)",
    "SELECT * FROM generate_series(1, 10)",
])
def test_table_allowlist_enforced(sql):
    with pytest.raises(SQLGuardError):
        check(sql)


def test_cte_name_is_not_a_table():
    r = check("WITH recent AS (SELECT * FROM orders) SELECT * FROM recent")
    assert r.tables == {"orders"}


# ---------- dangerous functions ----------
@pytest.mark.parametrize("sql", [
    "SELECT pg_sleep(10)",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT pg_ls_dir('/')",
    "SELECT pg_terminate_backend(1)",
    "SELECT lo_import('/etc/passwd')",
    "SELECT set_config('statement_timeout', '0', false)",
    "SELECT current_setting('server_version')",
    "SELECT * FROM orders WHERE order_id = (SELECT pg_sleep(5)::text)",
    "SELECT query_to_xml('select * from pg_user', true, true, '')",
    "SELECT version()",
    "SELECT current_user",
    "SELECT current_database()",
    "SELECT current_schema()",
])
def test_dangerous_functions_rejected(sql):
    with pytest.raises(SQLGuardError):
        check(sql)


# ---------- blocked columns ----------
@pytest.mark.parametrize("sql", [
    "SELECT review_comment_message FROM order_reviews",
    "SELECT r.review_comment_title FROM order_reviews r",
    "SELECT lower(review_comment_message) FROM order_reviews",
])
def test_blocked_columns_rejected(sql):
    with pytest.raises(SQLGuardError) as e:
        check(sql)
    assert e.value.code == "column_not_allowed"


# ---------- input hygiene ----------
@pytest.mark.parametrize("sql", ["", "   ", ";", "-- just a comment", "SELEC * FRM orders", "SELECT FROM WHERE"])
def test_garbage_rejected(sql):
    with pytest.raises(SQLGuardError):
        check(sql)


def test_too_long_rejected():
    with pytest.raises(SQLGuardError) as e:
        check("SELECT " + "1," * 5000 + "1")
    assert e.value.code == "too_long"


def test_comment_cannot_hide_second_statement():
    with pytest.raises(SQLGuardError):
        check("SELECT 1 /* x */ ; /* y */ DROP TABLE orders")


# ---------- LIMIT enforcement ----------
def test_limit_added_when_missing():
    r = check("SELECT * FROM orders", max_rows=50)
    assert r.limit_applied and "LIMIT 50" in r.sql


def test_small_limit_kept():
    r = check("SELECT * FROM orders LIMIT 10", max_rows=50)
    assert not r.limit_applied and "LIMIT 10" in r.sql


def test_large_limit_capped():
    r = check("SELECT * FROM orders LIMIT 999999", max_rows=50)
    assert r.limit_applied and "LIMIT 50" in r.sql and "999999" not in r.sql


def test_limit_all_replaced():
    r = check("SELECT * FROM orders LIMIT ALL", max_rows=50)
    assert "LIMIT 50" in r.sql


def test_union_gets_limit():
    r = check("SELECT order_id FROM orders UNION SELECT order_id FROM order_items", max_rows=50)
    assert "LIMIT 50" in r.sql
