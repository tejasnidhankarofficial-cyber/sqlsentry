-- Olist Brazilian E-Commerce: 8 tables (geolocation is intentionally not loaded).
-- Column order matches the Kaggle CSVs so COPY ... CSV HEADER works directly.

CREATE TABLE customers (
    customer_id              text PRIMARY KEY,   -- one per ORDER, not per person
    customer_unique_id       text NOT NULL,      -- identifies the actual person
    customer_zip_code_prefix text,
    customer_city            text,
    customer_state           text
);

CREATE TABLE sellers (
    seller_id              text PRIMARY KEY,
    seller_zip_code_prefix text,
    seller_city            text,
    seller_state           text
);

CREATE TABLE products (
    product_id                 text PRIMARY KEY,
    product_category_name      text,             -- Portuguese
    product_name_length        integer,
    product_description_length integer,
    product_photos_qty         integer,
    product_weight_g           integer,
    product_length_cm          integer,
    product_height_cm          integer,
    product_width_cm           integer
);

CREATE TABLE product_category_translation (
    product_category_name         text PRIMARY KEY,
    product_category_name_english text
);

CREATE TABLE orders (
    order_id                       text PRIMARY KEY,
    customer_id                    text NOT NULL REFERENCES customers (customer_id),
    order_status                   text,
    order_purchase_timestamp       timestamp,
    order_approved_at              timestamp,
    order_delivered_carrier_date   timestamp,
    order_delivered_customer_date  timestamp,
    order_estimated_delivery_date  timestamp
);

CREATE TABLE order_items (
    order_id            text NOT NULL REFERENCES orders (order_id),
    order_item_id       integer NOT NULL,
    product_id          text REFERENCES products (product_id),
    seller_id           text REFERENCES sellers (seller_id),
    shipping_limit_date timestamp,
    price               numeric(10, 2),
    freight_value       numeric(10, 2),
    PRIMARY KEY (order_id, order_item_id)
);

CREATE TABLE order_payments (
    order_id             text NOT NULL REFERENCES orders (order_id),
    payment_sequential   integer NOT NULL,
    payment_type         text,
    payment_installments integer,
    payment_value        numeric(10, 2),
    PRIMARY KEY (order_id, payment_sequential)
);

-- review_id is NOT unique in the source data, so there is no primary key.
CREATE TABLE order_reviews (
    review_id               text,
    order_id                text NOT NULL REFERENCES orders (order_id),
    review_score            integer,
    review_comment_title    text,
    review_comment_message  text,
    review_creation_date    timestamp,
    review_answer_timestamp timestamp
);

CREATE INDEX idx_orders_customer   ON orders (customer_id);
CREATE INDEX idx_orders_purchase   ON orders (order_purchase_timestamp);
CREATE INDEX idx_items_product     ON order_items (product_id);
CREATE INDEX idx_items_seller      ON order_items (seller_id);
CREATE INDEX idx_reviews_order     ON order_reviews (order_id);
CREATE INDEX idx_customers_unique  ON customers (customer_unique_id);
