#!/bin/bash
# Loads the Olist CSVs from ./data into the running Postgres container.
# Usage: ./scripts/load_data.sh   (after `docker compose up -d db` and CSVs are in ./data)
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

declare -a LOAD=(
  "customers:olist_customers_dataset.csv"
  "sellers:olist_sellers_dataset.csv"
  "products:olist_products_dataset.csv"
  "product_category_translation:product_category_name_translation.csv"
  "orders:olist_orders_dataset.csv"
  "order_items:olist_order_items_dataset.csv"
  "order_payments:olist_order_payments_dataset.csv"
  "order_reviews:olist_order_reviews_dataset.csv"
)

for pair in "${LOAD[@]}"; do
  f="data/${pair#*:}"
  [[ -f "$f" ]] || { echo "Missing $f - download the Olist dataset into ./data first" >&2; exit 1; }
done

psql_exec() { docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"; }

psql_exec -c "TRUNCATE order_reviews, order_payments, order_items, orders, products, product_category_translation, sellers, customers CASCADE;"

for pair in "${LOAD[@]}"; do
  table="${pair%%:*}"; file="${pair#*:}"
  echo "Loading $table <- $file"
  psql_exec -c "\copy $table FROM '/data/$file' WITH (FORMAT csv, HEADER true)"
done

psql_exec -c "ANALYZE;"
echo "Row counts:"
psql_exec -c "SELECT 'customers' t, count(*) FROM customers UNION ALL SELECT 'sellers', count(*) FROM sellers UNION ALL SELECT 'products', count(*) FROM products UNION ALL SELECT 'orders', count(*) FROM orders UNION ALL SELECT 'order_items', count(*) FROM order_items UNION ALL SELECT 'order_payments', count(*) FROM order_payments UNION ALL SELECT 'order_reviews', count(*) FROM order_reviews UNION ALL SELECT 'translation', count(*) FROM product_category_translation;"
