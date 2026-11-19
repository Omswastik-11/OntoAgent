"""Neo4j graph ingestion script: analytics.* / CSVs -> Neo4j knowledge graph.

Purpose:
    Extracts entities and relationships from PostgreSQL analytics schema (or fallback CSVs)
    and batch-loads them into Neo4j using UNWIND Cypher queries with uniqueness constraints.
"""

import argparse
import csv
import gzip
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
from neo4j import GraphDatabase
import psycopg

from ontoagent.config import get_settings


def create_constraints_and_indexes(session) -> None:
    """Create uniqueness constraints and indexes in Neo4j."""
    constraints = [
        "CREATE CONSTRAINT customer_unique IF NOT EXISTS FOR (c:Customer) REQUIRE c.customer_id IS UNIQUE;",
        "CREATE CONSTRAINT order_unique IF NOT EXISTS FOR (o:Order) REQUIRE o.order_id IS UNIQUE;",
        "CREATE CONSTRAINT seller_unique IF NOT EXISTS FOR (s:Seller) REQUIRE s.seller_id IS UNIQUE;",
        "CREATE CONSTRAINT product_unique IF NOT EXISTS FOR (p:Product) REQUIRE p.product_id IS UNIQUE;",
        "CREATE CONSTRAINT category_unique IF NOT EXISTS FOR (cat:Category) REQUIRE cat.name IS UNIQUE;",
        "CREATE CONSTRAINT review_unique IF NOT EXISTS FOR (r:Review) REQUIRE r.review_id IS UNIQUE;",
    ]
    for c in constraints:
        try:
            session.run(c)
        except Exception as e:
            print(f"Constraint note: {e}")


def batch_unwind(session, cypher: str, items: List[Dict[str, Any]], batch_size: int = 2000) -> None:
    """Execute UNWIND Cypher query in batches."""
    for i in range(0, len(items), batch_size):
        chunk = items[i : i + batch_size]
        session.run(cypher, {"batch": chunk})


def load_neo4j(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    pg_url: str,
    data_dir_str: str = "data/sample",
) -> Dict[str, int]:
    """Execute full Neo4j graph load from PostgreSQL or CSV fallback."""
    print(f"Connecting to Neo4j: {neo4j_uri}")
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    driver.verify_connectivity()

    # Step 1: Extract data from PostgreSQL (or CSV fallback)
    customers = []
    sellers = []
    products = []
    orders = []
    order_items = []
    reviews = []

    pg_connected = False
    try:
        with psycopg.connect(pg_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                print("Extracting entities from PostgreSQL analytics schema...")
                # Customers
                cur.execute("SELECT customer_id, customer_unique_id, city, state, region FROM analytics.dim_customer;")
                customers = [
                    {"customer_id": r[0], "customer_unique_id": r[1], "city": r[2] or "", "state": r[3] or "", "region": r[4] or ""}
                    for r in cur.fetchall()
                ]

                # Sellers
                cur.execute("SELECT seller_id, seller_city, seller_state, seller_region FROM analytics.dim_seller;")
                sellers = [
                    {"seller_id": r[0], "city": r[1] or "", "state": r[2] or "", "region": r[3] or ""}
                    for r in cur.fetchall()
                ]

                # Products
                cur.execute("SELECT product_id, category_en, category_group, weight_g FROM analytics.dim_product;")
                products = [
                    {"product_id": r[0], "category_en": r[1] or "other", "category_group": r[2] or "other", "weight_g": r[3] or 0}
                    for r in cur.fetchall()
                ]

                # Orders
                cur.execute(
                    """
                    SELECT order_id, customer_id, order_status, purchase_month::text, delivered_month::text,
                           is_delivered, is_late, delay_days, items_total::float, freight_total::float, order_value::float
                    FROM analytics.fct_orders;
                    """
                )
                orders = [
                    {
                        "order_id": r[0],
                        "customer_id": r[1],
                        "status": r[2],
                        "purchase_month": r[3] or "",
                        "delivered_month": r[4] or "",
                        "is_delivered": bool(r[5]),
                        "is_late": bool(r[6]) if r[6] is not None else False,
                        "delay_days": r[7] or 0,
                        "items_total": r[8] or 0.0,
                        "freight_total": r[9] or 0.0,
                        "order_value": r[10] or 0.0,
                    }
                    for r in cur.fetchall()
                ]

                # Order Items
                cur.execute(
                    """
                    SELECT order_id, order_item_id, product_id, seller_id, price::float, freight_value::float, handoff_late, handoff_delay_days
                    FROM analytics.fct_order_items;
                    """
                )
                order_items = [
                    {
                        "order_id": r[0],
                        "order_item_id": r[1],
                        "product_id": r[2],
                        "seller_id": r[3],
                        "price": r[4] or 0.0,
                        "freight_value": r[5] or 0.0,
                        "handoff_late": bool(r[6]) if r[6] is not None else False,
                        "handoff_delay_days": r[7] or 0,
                    }
                    for r in cur.fetchall()
                ]

                # Reviews
                cur.execute("SELECT review_id, order_id, review_score FROM analytics.fct_reviews;")
                reviews = [
                    {"review_id": r[0], "order_id": r[1], "score": r[2]}
                    for r in cur.fetchall()
                ]
                pg_connected = True
    except Exception as e:
        print(f"PostgreSQL extract skipped or failed ({e}). Attempting CSV fallback...")

    if not pg_connected:
        # Fallback to CSV loading
        data_dir = Path(data_dir_str)
        print(f"Loading from fallback CSVs in {data_dir}...")
        # (Customer CSV)
        cust_file = data_dir / "olist_customers_dataset.csv.gz"
        if cust_file.exists():
            with gzip.open(cust_file, "rt", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    customers.append({
                        "customer_id": r["customer_id"],
                        "customer_unique_id": r["customer_unique_id"],
                        "city": r.get("customer_city", ""),
                        "state": r.get("customer_state", ""),
                        "region": "Southeast" if r.get("customer_state") in ["SP", "RJ", "MG", "ES"] else "Other",
                    })
        # (Sellers CSV)
        seller_file = data_dir / "olist_sellers_dataset.csv.gz"
        if seller_file.exists():
            with gzip.open(seller_file, "rt", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    sellers.append({
                        "seller_id": r["seller_id"],
                        "city": r.get("seller_city", ""),
                        "state": r.get("seller_state", ""),
                        "region": "Southeast" if r.get("seller_state") in ["SP", "RJ", "MG", "ES"] else "Other",
                    })

    # Step 2: Build Unique Categories
    categories_map = {}
    for p in products:
        c_name = p["category_en"]
        if c_name not in categories_map:
            categories_map[c_name] = {
                "name": c_name,
                "category_en": c_name,
                "category_group": p["category_group"],
            }
    categories = list(categories_map.values())

    # Step 3: Load into Neo4j
    counts: Dict[str, int] = {}
    with driver.session() as session:
        print("Clearing existing Neo4j graph data...")
        session.run("MATCH (n) DETACH DELETE n;")

        print("Creating constraints...")
        create_constraints_and_indexes(session)

        # 1. Customers
        print(f"Loading {len(customers):,} Customer nodes...")
        batch_unwind(
            session,
            """
            UNWIND $batch AS row
            MERGE (c:Customer {customer_id: row.customer_id})
            SET c.customer_unique_id = row.customer_unique_id,
                c.city = row.city,
                c.state = row.state,
                c.region = row.region;
            """,
            customers,
        )

        # 2. Sellers
        print(f"Loading {len(sellers):,} Seller nodes...")
        batch_unwind(
            session,
            """
            UNWIND $batch AS row
            MERGE (s:Seller {seller_id: row.seller_id})
            SET s.city = row.city,
                s.state = row.state,
                s.region = row.region;
            """,
            sellers,
        )

        # 3. Categories
        print(f"Loading {len(categories):,} Category nodes...")
        batch_unwind(
            session,
            """
            UNWIND $batch AS row
            MERGE (cat:Category {name: row.name})
            SET cat.category_en = row.category_en,
                cat.category_group = row.category_group;
            """,
            categories,
        )

        # 4. Products & Category Relationships
        print(f"Loading {len(products):,} Product nodes & Category relationships...")
        batch_unwind(
            session,
            """
            UNWIND $batch AS row
            MERGE (p:Product {product_id: row.product_id})
            SET p.category_en = row.category_en,
                p.category_group = row.category_group,
                p.weight_g = row.weight_g
            WITH p, row
            MATCH (cat:Category {name: row.category_en})
            MERGE (p)-[:IN_CATEGORY]->(cat)
            MERGE (p)-[:BELONGS_TO]->(cat);
            """,
            products,
        )

        # 5. Orders & PLACED / SHIPPED_AS Relationships
        print(f"Loading {len(orders):,} Order & Shipment nodes...")
        batch_unwind(
            session,
            """
            UNWIND $batch AS row
            MERGE (o:Order {order_id: row.order_id})
            SET o.status = row.status,
                o.purchase_month = row.purchase_month,
                o.delivered_month = row.delivered_month,
                o.is_delivered = row.is_delivered,
                o.is_late = row.is_late,
                o.delay_days = row.delay_days,
                o.items_total = row.items_total,
                o.freight_total = row.freight_total,
                o.order_value = row.order_value
            WITH o, row
            MATCH (c:Customer {customer_id: row.customer_id})
            MERGE (c)-[:PLACED]->(o)
            WITH o, row
            MERGE (sh:Shipment {shipment_id: 'sh_' + row.order_id})
            SET sh.order_id = row.order_id,
                sh.is_late = row.is_late,
                sh.delay_days = row.delay_days
            MERGE (o)-[:SHIPPED_AS]->(sh);
            """,
            orders,
        )

        # 6. Order Items: CONTAINS, FULFILLS, SOLD
        print(f"Loading {len(order_items):,} Item relationships (CONTAINS, FULFILLS, SOLD)...")
        batch_unwind(
            session,
            """
            UNWIND $batch AS row
            MATCH (o:Order {order_id: row.order_id})
            MATCH (p:Product {product_id: row.product_id})
            MATCH (s:Seller {seller_id: row.seller_id})
            MERGE (o)-[c:CONTAINS {order_item_id: row.order_item_id}]->(p)
            SET c.price = row.price,
                c.freight_value = row.freight_value
            MERGE (s)-[:FULFILLS]->(o)
            MERGE (s)-[:SOLD]->(p);
            """,
            order_items,
        )

        # 7. Reviews: Review nodes & HAS_REVIEW
        print(f"Loading {len(reviews):,} Review nodes & HAS_REVIEW relationships...")
        batch_unwind(
            session,
            """
            UNWIND $batch AS row
            MERGE (r:Review {review_id: row.review_id})
            SET r.order_id = row.order_id,
                r.score = row.score
            WITH r, row
            MATCH (o:Order {order_id: row.order_id})
            MERGE (o)-[:HAS_REVIEW]->(r);
            """,
            reviews,
        )

        # Validate Counts
        count_queries = {
            "(:Customer)": "MATCH (n:Customer) RETURN count(n) AS c;",
            "(:Seller)": "MATCH (n:Seller) RETURN count(n) AS c;",
            "(:Product)": "MATCH (n:Product) RETURN count(n) AS c;",
            "(:Category)": "MATCH (n:Category) RETURN count(n) AS c;",
            "(:Order)": "MATCH (n:Order) RETURN count(n) AS c;",
            "(:Shipment)": "MATCH (n:Shipment) RETURN count(n) AS c;",
            "(:Review)": "MATCH (n:Review) RETURN count(n) AS c;",
            "[:PLACED]": "MATCH ()-[r:PLACED]->() RETURN count(r) AS c;",
            "[:CONTAINS]": "MATCH ()-[r:CONTAINS]->() RETURN count(r) AS c;",
            "[:FULFILLS]": "MATCH ()-[r:FULFILLS]->() RETURN count(r) AS c;",
            "[:SOLD]": "MATCH ()-[r:SOLD]->() RETURN count(r) AS c;",
            "[:SHIPPED_AS]": "MATCH ()-[r:SHIPPED_AS]->() RETURN count(r) AS c;",
            "[:HAS_REVIEW]": "MATCH ()-[r:HAS_REVIEW]->() RETURN count(r) AS c;",
            "[:IN_CATEGORY]": "MATCH ()-[r:IN_CATEGORY]->() RETURN count(r) AS c;",
        }

        for label, q in count_queries.items():
            res = session.run(q).single()
            counts[label] = res["c"] if res else 0

    driver.close()

    print("\n" + "=" * 50)
    print("Neo4j Knowledge Graph Ingestion Summary")
    print("=" * 50)
    for label, cnt in counts.items():
        print(f"  {label:<25} : {cnt:>6,} elements")
    print("=" * 50 + "\n")

    return counts


def main():
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Ingest PostgreSQL analytics tables into Neo4j Knowledge Graph.")
    parser.add_argument("--neo4j-uri", default=settings.neo4j_uri, help="Neo4j Bolt URI")
    parser.add_argument("--neo4j-user", default=settings.neo4j_user, help="Neo4j Username")
    parser.add_argument("--neo4j-password", default=settings.neo4j_password, help="Neo4j Password")
    parser.add_argument("--pg-url", default=settings.postgres_ro_url, help="PostgreSQL Read-Only URL")
    parser.add_argument("--data-dir", default="data/sample", help="Fallback sample data directory")
    args = parser.parse_args()

    try:
        load_neo4j(
            neo4j_uri=args.neo4j_uri,
            neo4j_user=args.neo4j_user,
            neo4j_password=args.neo4j_password,
            pg_url=args.pg_url,
            data_dir_str=args.data_dir,
        )
    except Exception as e:
        print(f"Error during Neo4j ingestion: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
