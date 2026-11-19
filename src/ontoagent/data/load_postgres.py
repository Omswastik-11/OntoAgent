"""Database ingestion script: CSVs -> raw.* -> analytics.* -> pii.customer_vault.

Purpose:
    Loads sample/raw dataset files into PostgreSQL raw.* tables, executes
    build_analytics.sql to build modeled analytics tables, and generates
    deterministic synthetic PII to populate pii.customer_vault and analytics.dim_customer.
"""

import argparse
import csv
import gzip
from pathlib import Path
import sys
from typing import Dict, List, Optional
import psycopg

from ontoagent.config import get_settings
from ontoagent.data.synth_pii import generate_synthetic_pii

RAW_TABLE_SCHEMAS = {
    "olist_customers": """
        CREATE TABLE IF NOT EXISTS raw.olist_customers (
            customer_id TEXT PRIMARY KEY,
            customer_unique_id TEXT NOT NULL,
            customer_zip_code_prefix TEXT,
            customer_city TEXT,
            customer_state TEXT
        );
    """,
    "olist_order_items": """
        CREATE TABLE IF NOT EXISTS raw.olist_order_items (
            order_id TEXT NOT NULL,
            order_item_id TEXT NOT NULL,
            product_id TEXT NOT NULL,
            seller_id TEXT NOT NULL,
            shipping_limit_date TEXT,
            price TEXT,
            freight_value TEXT
        );
    """,
    "olist_order_payments": """
        CREATE TABLE IF NOT EXISTS raw.olist_order_payments (
            order_id TEXT NOT NULL,
            payment_sequential TEXT NOT NULL,
            payment_type TEXT,
            payment_installments TEXT,
            payment_value TEXT
        );
    """,
    "olist_order_reviews": """
        CREATE TABLE IF NOT EXISTS raw.olist_order_reviews (
            review_id TEXT NOT NULL,
            order_id TEXT NOT NULL,
            review_score TEXT,
            review_comment_title TEXT,
            review_comment_message TEXT,
            review_creation_date TEXT,
            review_answer_timestamp TEXT
        );
    """,
    "olist_orders": """
        CREATE TABLE IF NOT EXISTS raw.olist_orders (
            order_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            order_status TEXT,
            order_purchase_timestamp TEXT,
            order_approved_at TEXT,
            order_delivered_carrier_date TEXT,
            order_delivered_customer_date TEXT,
            order_estimated_delivery_date TEXT
        );
    """,
    "olist_products": """
        CREATE TABLE IF NOT EXISTS raw.olist_products (
            product_id TEXT PRIMARY KEY,
            product_category_name TEXT,
            product_name_lenght TEXT,
            product_description_lenght TEXT,
            product_photos_qty TEXT,
            product_weight_g TEXT,
            product_length_cm TEXT,
            product_height_cm TEXT,
            product_width_cm TEXT
        );
    """,
    "olist_sellers": """
        CREATE TABLE IF NOT EXISTS raw.olist_sellers (
            seller_id TEXT PRIMARY KEY,
            seller_zip_code_prefix TEXT,
            seller_city TEXT,
            seller_state TEXT
        );
    """,
    "product_category_name_translation": """
        CREATE TABLE IF NOT EXISTS raw.product_category_name_translation (
            product_category_name TEXT PRIMARY KEY,
            product_category_name_english TEXT
        );
    """,
}

FILE_TO_TABLE = {
    "olist_customers_dataset": "olist_customers",
    "olist_order_items_dataset": "olist_order_items",
    "olist_order_payments_dataset": "olist_order_payments",
    "olist_order_reviews_dataset": "olist_order_reviews",
    "olist_orders_dataset": "olist_orders",
    "olist_products_dataset": "olist_products",
    "olist_sellers_dataset": "olist_sellers",
    "product_category_name_translation": "product_category_name_translation",
}


def find_data_file(data_dir: Path, base_name: str) -> Optional[Path]:
    """Find .csv or .csv.gz file matching base_name."""
    gz_path = data_dir / f"{base_name}.csv.gz"
    if gz_path.exists():
        return gz_path
    csv_path = data_dir / f"{base_name}.csv"
    if csv_path.exists():
        return csv_path
    return None


def open_csv_reader(path: Path):
    """Open a CSV file or GZipped CSV file as a DictReader."""
    if path.suffix == ".gz":
        f = gzip.open(path, "rt", encoding="utf-8")
    else:
        f = open(path, "r", encoding="utf-8")
    reader = csv.DictReader(f)
    return f, reader


def load_raw_table(conn: psycopg.Connection, table_name: str, file_path: Path) -> int:
    """Load records from CSV/GZ into raw table using psycopg."""
    f, reader = open_csv_reader(file_path)
    fieldnames = reader.fieldnames or []
    cols = ", ".join(fieldnames)
    placeholders = ", ".join(["%s"] * len(fieldnames))
    query = f"INSERT INTO raw.{table_name} ({cols}) VALUES ({placeholders});"

    rows: List[tuple] = []
    for r in reader:
        rows.append(tuple(r.get(col, "") for col in fieldnames))
    f.close()

    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE raw.{table_name} CASCADE;")
        if rows:
            cur.executemany(query, rows)

    return len(rows)


def load_postgres(data_dir_str: str, db_url: str) -> Dict[str, int]:
    """Execute complete PostgreSQL load and transform pipeline."""
    data_dir = Path(data_dir_str)
    if not data_dir.exists():
        alt_dir = Path("data/sample")
        if alt_dir.exists():
            data_dir = alt_dir
        else:
            raise FileNotFoundError(f"Data directory {data_dir_str} not found.")

    print(f"Connecting to PostgreSQL: {db_url.split('@')[-1]}")
    counts: Dict[str, int] = {}

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            # Step 1: Ensure schemas exist
            cur.execute("CREATE SCHEMA IF NOT EXISTS raw;")
            cur.execute("CREATE SCHEMA IF NOT EXISTS analytics;")
            cur.execute("CREATE SCHEMA IF NOT EXISTS pii;")

            # Step 2: Create raw tables
            for tbl, ddl in RAW_TABLE_SCHEMAS.items():
                cur.execute(ddl)

        # Step 3: Load raw data from CSVs
        print(f"Loading raw CSVs from {data_dir}...")
        for file_key, tbl_name in FILE_TO_TABLE.items():
            fpath = find_data_file(data_dir, file_key)
            if not fpath:
                print(f"Warning: Could not find file for {file_key}")
                continue
            cnt = load_raw_table(conn, tbl_name, fpath)
            counts[f"raw.{tbl_name}"] = cnt
            print(f"  Loaded raw.{tbl_name}: {cnt:,} rows")

        # Step 4: Execute build_analytics.sql
        sql_path = Path("src/ontoagent/data/build_analytics.sql")
        print(f"Executing {sql_path}...")
        sql_script = sql_path.read_text(encoding="utf-8")
        with conn.cursor() as cur:
            cur.execute(sql_script)

        # Step 5: Create and populate pii.customer_vault and analytics.dim_customer
        print("Populating synthetic PII vault (pii.customer_vault) and dim_customer...")
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pii.customer_vault (
                    customer_unique_id TEXT PRIMARY KEY,
                    cpf TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    email TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
            cur.execute("GRANT SELECT ON pii.customer_vault TO ontoagent_app, ontoagent_admin;")

            # Read all unique customers from raw.olist_customers
            cur.execute(
                """
                SELECT c.customer_id, c.customer_unique_id, c.customer_city, c.customer_state, COALESCE(r.region, 'Unknown')
                FROM raw.olist_customers c
                LEFT JOIN analytics.dim_state_region r ON c.customer_state = r.state;
                """
            )
            raw_customers = cur.fetchall()

            # Generate synthetic PII deterministically
            vault_map: Dict[str, Dict[str, str]] = {}
            for _, uniq_id, _, _, _ in raw_customers:
                if uniq_id not in vault_map:
                    vault_map[uniq_id] = generate_synthetic_pii(uniq_id)

            # Insert into pii.customer_vault
            cur.execute("TRUNCATE TABLE pii.customer_vault;")
            vault_rows = [
                (uniq_id, pii_data["cpf"], pii_data["phone"], pii_data["email"])
                for uniq_id, pii_data in vault_map.items()
            ]
            cur.executemany(
                "INSERT INTO pii.customer_vault (customer_unique_id, cpf, phone, email) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING;",
                vault_rows,
            )
            counts["pii.customer_vault"] = len(vault_rows)

            # Insert into analytics.dim_customer
            cur.execute("TRUNCATE TABLE analytics.dim_customer;")
            dim_cust_rows = [
                (
                    cid,
                    uniq_id,
                    city,
                    state,
                    region,
                    vault_map[uniq_id]["email"],
                    vault_map[uniq_id]["phone"],
                    vault_map[uniq_id]["cpf"],
                )
                for cid, uniq_id, city, state, region in raw_customers
            ]
            cur.executemany(
                """
                INSERT INTO analytics.dim_customer (
                    customer_id, customer_unique_id, city, state, region, email, phone, cpf
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (customer_id) DO NOTHING;
                """,
                dim_cust_rows,
            )
            counts["analytics.dim_customer"] = len(dim_cust_rows)

        # Step 6: Validate row counts and print summary
        analytics_tables = [
            "analytics.dim_state_region",
            "analytics.dim_seller",
            "analytics.dim_product",
            "analytics.fct_orders",
            "analytics.fct_order_items",
            "analytics.fct_reviews",
            "analytics.fct_payments",
            "analytics.dim_customer",
        ]
        with conn.cursor() as cur:
            for tbl in analytics_tables:
                cur.execute(f"SELECT COUNT(*) FROM {tbl};")
                row_cnt = cur.fetchone()[0]
                counts[tbl] = row_cnt

    print("\n" + "=" * 50)
    print("PostgreSQL Ingestion & Modeling Summary")
    print("=" * 50)
    for tbl, cnt in counts.items():
        print(f"  {tbl:<35} : {cnt:>6,} rows")
    print("=" * 50 + "\n")

    return counts


def main():
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Ingest sample CSVs into PostgreSQL raw and analytics schemas.")
    parser.add_argument("--data-dir", default="data/sample", help="Directory containing sample CSV/GZ files")
    parser.add_argument("--db-url", default=settings.postgres_admin_url, help="PostgreSQL Admin URL")
    args = parser.parse_args()

    try:
        load_postgres(data_dir_str=args.data_dir, db_url=args.db_url)
    except Exception as e:
        print(f"Error during PostgreSQL ingestion: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
