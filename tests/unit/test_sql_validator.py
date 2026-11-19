"""Comprehensive tests for SQL validator and adversarial attack corpus (Threat T4)."""

import pytest
from ontoagent.guards.sql_validator import validate_sql

BENIGN_QUERIES = [
    "SELECT COUNT(*) FROM analytics.fct_orders;",
    "SELECT order_status, COUNT(*) FROM analytics.fct_orders GROUP BY order_status;",
    "SELECT AVG(is_late::int) FROM analytics.fct_orders WHERE is_delivered;",
    "SELECT seller_region, COUNT(*) FROM analytics.dim_seller GROUP BY seller_region;",
    "SELECT o.order_id, o.order_value FROM analytics.fct_orders o LIMIT 10;",
    "SELECT o.delivered_month, COUNT(DISTINCT o.order_id) FROM analytics.fct_orders o WHERE o.is_delivered GROUP BY 1;",
    "SELECT category_group, AVG(freight_value) FROM analytics.fct_order_items GROUP BY category_group;",
    "SELECT payment_type, SUM(payment_value) FROM analytics.fct_payments GROUP BY payment_type;",
    "SELECT review_score, COUNT(*) FROM analytics.fct_reviews GROUP BY review_score;",
    "SELECT state, region FROM analytics.dim_state_region LIMIT 20;",
    "SELECT o.order_id, i.price FROM analytics.fct_orders o JOIN analytics.fct_order_items i USING (order_id) LIMIT 5;",
    "SELECT customer_state, COUNT(DISTINCT order_id) FROM analytics.fct_orders GROUP BY customer_state;",
    "SELECT seller_id, COUNT(*) AS units FROM analytics.fct_order_items GROUP BY seller_id ORDER BY units DESC LIMIT 20;",
    "SELECT purchase_month, SUM(order_value) FROM analytics.fct_orders GROUP BY purchase_month;",
    "SELECT * FROM analytics.dim_seller LIMIT 10;",
    "WITH late_orders AS (SELECT order_id FROM analytics.fct_orders WHERE is_late) SELECT COUNT(*) FROM late_orders;",
    "SELECT o.order_id, r.review_score FROM analytics.fct_orders o JOIN analytics.fct_reviews r ON o.order_id = r.order_id LIMIT 10;",
    "SELECT transit_days, COUNT(*) FROM analytics.fct_orders WHERE is_delivered GROUP BY transit_days;",
    "SELECT handoff_late, COUNT(*) FROM analytics.fct_order_items WHERE handoff_late IS NOT NULL GROUP BY handoff_late;",
    "SELECT o.order_id FROM analytics.fct_orders o WHERE o.order_value > 500 LIMIT 15;",
    "SELECT seller_state, AVG(price) FROM analytics.fct_order_items GROUP BY seller_state HAVING COUNT(*) > 10;",
]

ATTACK_QUERIES = [
    # Non-select statement attacks (SEC_NOT_SELECT)
    ("DROP TABLE analytics.fct_orders;", "SEC_NOT_SELECT"),
    ("DELETE FROM analytics.fct_orders WHERE order_id = '123';", "SEC_NOT_SELECT"),
    ("UPDATE analytics.fct_orders SET is_late = FALSE;", "SEC_NOT_SELECT"),
    ("INSERT INTO analytics.fct_orders (order_id) VALUES ('x');", "SEC_NOT_SELECT"),
    ("TRUNCATE TABLE analytics.fct_orders;", "SEC_NOT_SELECT"),
    ("ALTER TABLE analytics.fct_orders DROP COLUMN is_late;", "SEC_NOT_SELECT"),
    ("CREATE TABLE analytics.hack (id INT);", "SEC_NOT_SELECT"),
    ("GRANT ALL PRIVILEGES ON analytics.fct_orders TO public;", "SEC_NOT_SELECT"),
    ("MERGE INTO analytics.fct_orders USING analytics.dim_seller ON 1=1 WHEN MATCHED THEN DELETE;", "SEC_NOT_SELECT"),
    ("COPY analytics.fct_orders TO '/tmp/leak.csv';", "SEC_NOT_SELECT"),
    
    # Multi-statement injection attacks (SEC_MULTI_STATEMENT)
    ("SELECT COUNT(*) FROM analytics.fct_orders; DROP TABLE analytics.fct_orders;", "SEC_MULTI_STATEMENT"),
    ("SELECT 1; DELETE FROM analytics.dim_seller;", "SEC_MULTI_STATEMENT"),
    ("SELECT * FROM analytics.fct_orders; --\nDROP TABLE analytics.fct_orders;", "SEC_MULTI_STATEMENT"),
    ("SELECT 1; UPDATE analytics.dim_seller SET seller_city = 'hacked';", "SEC_MULTI_STATEMENT"),
    ("SELECT 1; SELECT 2;", "SEC_MULTI_STATEMENT"),

    # Forbidden clauses (SEC_FORBIDDEN_CLAUSE)
    ("SELECT * INTO new_table FROM analytics.fct_orders;", "SEC_FORBIDDEN_CLAUSE"),
    ("SELECT * FROM analytics.fct_orders FOR UPDATE;", "SEC_FORBIDDEN_CLAUSE"),
    ("SELECT * FROM analytics.fct_orders FOR SHARE;", "SEC_FORBIDDEN_CLAUSE"),

    # Forbidden functions (SEC_FORBIDDEN_FUNCTION)
    ("SELECT pg_sleep(5);", "SEC_FORBIDDEN_FUNCTION"),
    ("SELECT pg_read_file('/etc/passwd');", "SEC_FORBIDDEN_FUNCTION"),
    ("SELECT current_setting('listen_addresses');", "SEC_FORBIDDEN_FUNCTION"),
    ("SELECT set_config('work_mem', '1GB', false);", "SEC_FORBIDDEN_FUNCTION"),
    ("SELECT dblink('host=evil.com', 'SELECT 1');", "SEC_FORBIDDEN_FUNCTION"),
    ("SELECT lo_export(1, '/tmp/leak');", "SEC_FORBIDDEN_FUNCTION"),
    ("SELECT txid_current();", "SEC_FORBIDDEN_FUNCTION"),
    ("SELECT query_to_xml('SELECT 1', true, false, '');", "SEC_FORBIDDEN_FUNCTION"),
    ("SELECT xpath('/x', '<x>1</x>');", "SEC_FORBIDDEN_FUNCTION"),
    ("SELECT generate_series(1, 1000000);", "SEC_FORBIDDEN_FUNCTION"),

    # Unauthorized tables (SEC_TABLE_DENIED or UNKNOWN_TABLE)
    ("SELECT * FROM information_schema.tables;", "SEC_TABLE_DENIED"),
    ("SELECT * FROM pg_catalog.pg_tables;", "SEC_TABLE_DENIED"),
    ("SELECT * FROM ops.refund_tickets;", "SEC_TABLE_DENIED"),
    ("SELECT * FROM kb.policy_chunks;", "SEC_TABLE_DENIED"),
    ("SELECT * FROM raw.olist_orders;", "SEC_TABLE_DENIED"),
    ("SELECT * FROM analytics.dim_customer;", "SEC_TABLE_DENIED"), # for analyst
    ("SELECT * FROM unknown_table;", "SEC_TABLE_DENIED"),

    # Denied columns for analyst (SEC_COLUMN_DENIED)
    ("SELECT comment_message FROM analytics.fct_reviews;", "SEC_COLUMN_DENIED"),
    ("SELECT r.comment_title FROM analytics.fct_reviews r;", "SEC_COLUMN_DENIED"),
    ("SELECT order_id, comment_message FROM analytics.fct_reviews;", "SEC_COLUMN_DENIED"),

    # Row policy violations for analyst (ROW_POLICY_VIOLATION)
    ("SELECT order_id FROM analytics.fct_orders;", "ROW_POLICY_VIOLATION"),
    ("SELECT order_id, order_value FROM analytics.fct_orders LIMIT 100;", "ROW_POLICY_VIOLATION"),
    ("SELECT seller_id, seller_city FROM analytics.dim_seller;", "ROW_POLICY_VIOLATION"),
]


@pytest.mark.parametrize("query", BENIGN_QUERIES)
def test_benign_queries_pass(query, ontology):
    res = validate_sql(query, role="analyst", onto=ontology)
    assert res.ok, f"Benign query failed: {query} with reasons: {res.reasons}"
    assert res.rewritten_sql is not None


@pytest.mark.parametrize("query,expected_code", ATTACK_QUERIES)
def test_attack_queries_blocked(query, expected_code, ontology):
    res = validate_sql(query, role="analyst", onto=ontology)
    assert not res.ok, f"Attack query was unexpectedly permitted: {query}"
    assert res.code == expected_code or res.code.startswith("SEC_"), (
        f"Expected code {expected_code}, got {res.code} for: {query}"
    )


def test_star_expansion_excludes_denied_columns(ontology):
    query = "SELECT * FROM analytics.fct_reviews LIMIT 5;"
    res = validate_sql(query, role="analyst", onto=ontology)
    assert res.ok
    assert "comment_title" not in res.rewritten_sql.lower()
    assert "comment_message" not in res.rewritten_sql.lower()


def test_limit_clamped_to_1000(ontology):
    query = "SELECT order_status, COUNT(*) FROM analytics.fct_orders GROUP BY 1 LIMIT 5000;"
    res = validate_sql(query, role="analyst", onto=ontology)
    assert res.ok
    assert "LIMIT 1000" in res.rewritten_sql.upper()
