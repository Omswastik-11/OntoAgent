-- build_analytics.sql
-- Modelled analytics tables built from raw schema

CREATE SCHEMA IF NOT EXISTS analytics;

-- 1. dim_state_region
CREATE TABLE IF NOT EXISTS analytics.dim_state_region (
    state CHAR(2) PRIMARY KEY,
    region TEXT NOT NULL
);

INSERT INTO analytics.dim_state_region (state, region) VALUES
('AC', 'North'), ('AP', 'North'), ('AM', 'North'), ('PA', 'North'), ('RO', 'North'), ('RR', 'North'), ('TO', 'North'),
('AL', 'Northeast'), ('BA', 'Northeast'), ('CE', 'Northeast'), ('MA', 'Northeast'), ('PB', 'Northeast'), ('PE', 'Northeast'), ('PI', 'Northeast'), ('RN', 'Northeast'), ('SE', 'Northeast'),
('DF', 'Center-West'), ('GO', 'Center-West'), ('MT', 'Center-West'), ('MS', 'Center-West'),
('ES', 'Southeast'), ('MG', 'Southeast'), ('RJ', 'Southeast'), ('SP', 'Southeast'),
('PR', 'South'), ('RS', 'South'), ('SC', 'South')
ON CONFLICT (state) DO UPDATE SET region = EXCLUDED.region;

-- 2. dim_seller
CREATE TABLE IF NOT EXISTS analytics.dim_seller (
    seller_id TEXT PRIMARY KEY,
    seller_city TEXT,
    seller_state CHAR(2),
    seller_region TEXT
);

-- 3. dim_product
CREATE TABLE IF NOT EXISTS analytics.dim_product (
    product_id TEXT PRIMARY KEY,
    category_pt TEXT,
    category_en TEXT,
    category_group TEXT NOT NULL DEFAULT 'other',
    weight_g INTEGER,
    photos_qty INTEGER,
    name_length INTEGER,
    description_length INTEGER
);

-- 4. fct_orders
CREATE TABLE IF NOT EXISTS analytics.fct_orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    customer_unique_id TEXT NOT NULL,
    customer_state CHAR(2),
    customer_region TEXT,
    order_status TEXT NOT NULL,
    purchase_ts TIMESTAMP NOT NULL,
    approved_ts TIMESTAMP,
    carrier_ts TIMESTAMP,
    delivered_ts TIMESTAMP,
    estimated_delivery_ts TIMESTAMP NOT NULL,
    purchase_month DATE NOT NULL,
    delivered_month DATE,
    is_delivered BOOLEAN NOT NULL DEFAULT FALSE,
    is_late BOOLEAN,
    delay_days INTEGER,
    transit_days INTEGER,
    item_count INTEGER NOT NULL DEFAULT 0,
    items_total NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    freight_total NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    order_value NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    payment_total NUMERIC(12,2) NOT NULL DEFAULT 0.00
);

CREATE INDEX IF NOT EXISTS fct_orders_delivered_month_idx ON analytics.fct_orders (delivered_month);
CREATE INDEX IF NOT EXISTS fct_orders_purchase_month_idx ON analytics.fct_orders (purchase_month);

-- 5. fct_order_items
CREATE TABLE IF NOT EXISTS analytics.fct_order_items (
    order_id TEXT NOT NULL,
    order_item_id INTEGER NOT NULL,
    product_id TEXT NOT NULL,
    seller_id TEXT NOT NULL,
    seller_state CHAR(2),
    seller_region TEXT,
    category_en TEXT,
    category_group TEXT NOT NULL DEFAULT 'other',
    shipping_limit_ts TIMESTAMP NOT NULL,
    carrier_ts TIMESTAMP,
    price NUMERIC(12,2) NOT NULL,
    freight_value NUMERIC(12,2) NOT NULL,
    handoff_late BOOLEAN,
    handoff_delay_days INTEGER,
    PRIMARY KEY (order_id, order_item_id)
);

CREATE INDEX IF NOT EXISTS fct_order_items_seller_region_idx ON analytics.fct_order_items (seller_region);
CREATE INDEX IF NOT EXISTS fct_order_items_category_group_idx ON analytics.fct_order_items (category_group);

-- 6. fct_reviews
CREATE TABLE IF NOT EXISTS analytics.fct_reviews (
    review_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    review_score SMALLINT NOT NULL CHECK (review_score BETWEEN 1 AND 5),
    comment_title TEXT,
    comment_message TEXT,
    created_ts TIMESTAMP NOT NULL,
    answered_ts TIMESTAMP NOT NULL,
    PRIMARY KEY (review_id, order_id)
);

-- 7. fct_payments
CREATE TABLE IF NOT EXISTS analytics.fct_payments (
    order_id TEXT NOT NULL,
    payment_sequential INTEGER NOT NULL,
    payment_type TEXT NOT NULL,
    installments INTEGER NOT NULL DEFAULT 1,
    payment_value NUMERIC(12,2) NOT NULL,
    PRIMARY KEY (order_id, payment_sequential)
);

-- 8. dim_customer
CREATE TABLE IF NOT EXISTS analytics.dim_customer (
    customer_id TEXT PRIMARY KEY,
    customer_unique_id TEXT NOT NULL,
    city TEXT,
    state CHAR(2),
    region TEXT,
    email TEXT,
    phone TEXT,
    cpf TEXT
);

-- ============================================================================
-- ETL Transformations: Populate analytics tables from raw tables
-- ============================================================================

-- Populate dim_seller
TRUNCATE TABLE analytics.dim_seller CASCADE;
INSERT INTO analytics.dim_seller (seller_id, seller_city, seller_state, seller_region)
SELECT 
    s.seller_id,
    s.seller_city,
    s.seller_state,
    COALESCE(r.region, 'Unknown')
FROM raw.olist_sellers s
LEFT JOIN analytics.dim_state_region r ON s.seller_state = r.state
ON CONFLICT (seller_id) DO NOTHING;

-- Populate dim_product
TRUNCATE TABLE analytics.dim_product CASCADE;
INSERT INTO analytics.dim_product (
    product_id, category_pt, category_en, category_group, weight_g, photos_qty, name_length, description_length
)
SELECT 
    p.product_id,
    p.product_category_name AS category_pt,
    COALESCE(t.product_category_name_english, p.product_category_name) AS category_en,
    CASE 
        WHEN COALESCE(t.product_category_name_english, p.product_category_name) IN ('telephony', 'computers_accessories', 'electronics', 'audio') THEN 'electronics'
        WHEN COALESCE(t.product_category_name_english, p.product_category_name) IN ('watches_gifts', 'fashion_bags_accessories', 'fashion_shoes') THEN 'fashion'
        WHEN COALESCE(t.product_category_name_english, p.product_category_name) IN ('bed_bath_table', 'furniture_decor', 'housewares', 'home_comfort') THEN 'home_furniture'
        WHEN COALESCE(t.product_category_name_english, p.product_category_name) IN ('health_beauty', 'perfumery') THEN 'health_beauty'
        WHEN COALESCE(t.product_category_name_english, p.product_category_name) IN ('sports_leisure') THEN 'sports_leisure'
        ELSE 'other'
    END AS category_group,
    NULLIF(p.product_weight_g, '')::INTEGER,
    NULLIF(p.product_photos_qty, '')::INTEGER,
    NULLIF(p.product_name_lenght, '')::INTEGER,
    NULLIF(p.product_description_lenght, '')::INTEGER
FROM raw.olist_products p
LEFT JOIN raw.product_category_name_translation t ON p.product_category_name = t.product_category_name
ON CONFLICT (product_id) DO NOTHING;

-- Populate fct_orders
TRUNCATE TABLE analytics.fct_orders CASCADE;
INSERT INTO analytics.fct_orders (
    order_id, customer_id, customer_unique_id, customer_state, customer_region,
    order_status, purchase_ts, approved_ts, carrier_ts, delivered_ts, estimated_delivery_ts,
    purchase_month, delivered_month, is_delivered, is_late, delay_days, transit_days,
    item_count, items_total, freight_total, order_value, payment_total
)
SELECT 
    o.order_id,
    o.customer_id,
    c.customer_unique_id,
    c.customer_state,
    COALESCE(r.region, 'Unknown') AS customer_region,
    o.order_status,
    o.order_purchase_timestamp::timestamp AS purchase_ts,
    NULLIF(o.order_approved_at, '')::timestamp AS approved_ts,
    NULLIF(o.order_delivered_carrier_date, '')::timestamp AS carrier_ts,
    NULLIF(o.order_delivered_customer_date, '')::timestamp AS delivered_ts,
    o.order_estimated_delivery_date::timestamp AS estimated_delivery_ts,
    DATE_TRUNC('month', o.order_purchase_timestamp::timestamp)::date AS purchase_month,
    CASE WHEN NULLIF(o.order_delivered_customer_date, '') IS NOT NULL 
         THEN DATE_TRUNC('month', o.order_delivered_customer_date::timestamp)::date 
         ELSE NULL END AS delivered_month,
    (o.order_status = 'delivered' AND NULLIF(o.order_delivered_customer_date, '') IS NOT NULL) AS is_delivered,
    CASE 
        WHEN NULLIF(o.order_delivered_customer_date, '') IS NOT NULL AND o.order_estimated_delivery_date IS NOT NULL 
        THEN (o.order_delivered_customer_date::timestamp > o.order_estimated_delivery_date::timestamp)
        ELSE NULL 
    END AS is_late,
    CASE 
        WHEN NULLIF(o.order_delivered_customer_date, '') IS NOT NULL AND o.order_estimated_delivery_date IS NOT NULL 
        THEN GREATEST(0, EXTRACT(DAY FROM (o.order_delivered_customer_date::timestamp - o.order_estimated_delivery_date::timestamp))::integer)
        ELSE NULL 
    END AS delay_days,
    CASE 
        WHEN NULLIF(o.order_delivered_customer_date, '') IS NOT NULL 
        THEN GREATEST(0, EXTRACT(DAY FROM (o.order_delivered_customer_date::timestamp - o.order_purchase_timestamp::timestamp))::integer)
        ELSE NULL 
    END AS transit_days,
    COALESCE(it.item_count, 0) AS item_count,
    COALESCE(it.items_total, 0.00) AS items_total,
    COALESCE(it.freight_total, 0.00) AS freight_total,
    COALESCE(it.items_total, 0.00) + COALESCE(it.freight_total, 0.00) AS order_value,
    COALESCE(pt.payment_total, 0.00) AS payment_total
FROM raw.olist_orders o
LEFT JOIN raw.olist_customers c ON o.customer_id = c.customer_id
LEFT JOIN analytics.dim_state_region r ON c.customer_state = r.state
LEFT JOIN (
    SELECT order_id, COUNT(*) AS item_count, SUM(price::numeric) AS items_total, SUM(freight_value::numeric) AS freight_total
    FROM raw.olist_order_items
    GROUP BY order_id
) it ON o.order_id = it.order_id
LEFT JOIN (
    SELECT order_id, SUM(payment_value::numeric) AS payment_total
    FROM raw.olist_order_payments
    GROUP BY order_id
) pt ON o.order_id = pt.order_id
ON CONFLICT (order_id) DO NOTHING;

-- Populate fct_order_items
TRUNCATE TABLE analytics.fct_order_items CASCADE;
INSERT INTO analytics.fct_order_items (
    order_id, order_item_id, product_id, seller_id, seller_state, seller_region,
    category_en, category_group, shipping_limit_ts, carrier_ts, price, freight_value,
    handoff_late, handoff_delay_days
)
SELECT 
    i.order_id,
    i.order_item_id::integer,
    i.product_id,
    i.seller_id,
    s.seller_state,
    s.seller_region,
    p.category_en,
    p.category_group,
    i.shipping_limit_date::timestamp AS shipping_limit_ts,
    NULLIF(o.order_delivered_carrier_date, '')::timestamp AS carrier_ts,
    i.price::numeric(12,2),
    i.freight_value::numeric(12,2),
    CASE 
        WHEN NULLIF(o.order_delivered_carrier_date, '') IS NOT NULL 
        THEN (o.order_delivered_carrier_date::timestamp > i.shipping_limit_date::timestamp)
        ELSE NULL 
    END AS handoff_late,
    CASE 
        WHEN NULLIF(o.order_delivered_carrier_date, '') IS NOT NULL 
        THEN GREATEST(0, EXTRACT(DAY FROM (o.order_delivered_carrier_date::timestamp - i.shipping_limit_date::timestamp))::integer)
        ELSE NULL 
    END AS handoff_delay_days
FROM raw.olist_order_items i
LEFT JOIN analytics.dim_seller s ON i.seller_id = s.seller_id
LEFT JOIN analytics.dim_product p ON i.product_id = p.product_id
LEFT JOIN raw.olist_orders o ON i.order_id = o.order_id
ON CONFLICT (order_id, order_item_id) DO NOTHING;

-- Populate fct_reviews
TRUNCATE TABLE analytics.fct_reviews CASCADE;
INSERT INTO analytics.fct_reviews (
    review_id, order_id, review_score, comment_title, comment_message, created_ts, answered_ts
)
SELECT DISTINCT ON (review_id, order_id)
    review_id,
    order_id,
    review_score::smallint,
    NULLIF(review_comment_title, ''),
    NULLIF(review_comment_message, ''),
    review_creation_date::timestamp,
    review_answer_timestamp::timestamp
FROM raw.olist_order_reviews
WHERE order_id IS NOT NULL AND review_id IS NOT NULL
ORDER BY review_id, order_id, review_answer_timestamp DESC
ON CONFLICT (review_id, order_id) DO NOTHING;

-- Populate fct_payments
TRUNCATE TABLE analytics.fct_payments CASCADE;
INSERT INTO analytics.fct_payments (
    order_id, payment_sequential, payment_type, installments, payment_value
)
SELECT 
    order_id,
    payment_sequential::integer,
    payment_type,
    COALESCE(payment_installments::integer, 1),
    payment_value::numeric(12,2)
FROM raw.olist_order_payments
ON CONFLICT (order_id, payment_sequential) DO NOTHING;

-- Grant privileges to read-only and operational roles
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO ontoagent_ro, ontoagent_app, ontoagent_ops;

