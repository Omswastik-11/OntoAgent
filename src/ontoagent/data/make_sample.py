"""Deterministic sample dataset generator for OntoAgent.

Purpose:
    Generates or extracts a 3,000 order sample dataset in data/sample/
    ensuring all golden-set criteria are satisfied:
    - At least 100 late orders in August 2018 with electronics items from Southeast sellers.
    - At least 20 sellers with >= 20 items.
    - Deterministic random seeding for 100% reproducibility.
"""

import csv
import gzip
from datetime import datetime, timedelta
from pathlib import Path
import random
from typing import Dict, List

from ontoagent.data.synth_pii import generate_synthetic_pii

SAMPLE_DIR = Path("data/sample")
RAW_DIR = Path("data/raw/olist")

REGIONS = {
    "North": ["AC", "AP", "AM", "PA", "RO", "RR", "TO"],
    "Northeast": ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"],
    "Center-West": ["DF", "GO", "MT", "MS"],
    "Southeast": ["ES", "MG", "RJ", "SP"],
    "South": ["PR", "RS", "SC"],
}

STATE_TO_REGION = {st: reg for reg, states in REGIONS.items() for st in states}


def generate_synthetic_sample(order_count: int = 3000, seed: int = 42) -> None:
    """Generate synthetic sample dataset satisfying all schema and eval requirements."""
    random.seed(seed)
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Sellers (50 sellers, top 25 high volume)
    sellers = []
    for i in range(1, 51):
        s_id = f"seller_{i:04d}"
        state = "SP" if i <= 35 else random.choice(["RJ", "MG", "PR", "SC", "BA", "RS"])
        sellers.append({
            "seller_id": s_id,
            "seller_zip_code_prefix": f"{random.randint(10000, 99999)}",
            "seller_city": "Sao Paulo" if state == "SP" else "Rio de Janeiro",
            "seller_state": state,
        })

    # 2. Products (100 products, 30 electronics)
    products = []
    categories = [
        ("telefonia", "telephony", "electronics"),
        ("informatica_acessorios", "computers_accessories", "electronics"),
        ("eletronicos", "electronics", "electronics"),
        ("audio", "audio", "electronics"),
        ("relogios_presentes", "watches_gifts", "fashion"),
        ("cama_mesa_banho", "bed_bath_table", "home_furniture"),
        ("beleza_saude", "health_beauty", "health_beauty"),
        ("esporte_lazer", "sports_leisure", "sports_leisure"),
    ]
    for i in range(1, 101):
        p_id = f"prod_{i:04d}"
        cat_pt, cat_en, cat_grp = categories[i % len(categories)]
        products.append({
            "product_id": p_id,
            "product_category_name": cat_pt,
            "product_name_lenght": random.randint(20, 60),
            "product_description_lenght": random.randint(100, 800),
            "product_photos_qty": random.randint(1, 6),
            "product_weight_g": random.randint(200, 5000),
            "product_length_cm": 20,
            "product_height_cm": 15,
            "product_width_cm": 15,
        })

    # Category translations
    translations = [
        {"product_category_name": c[0], "product_category_name_english": c[1]}
        for c in categories
    ]

    # 3. Orders, Items, Payments, Reviews, Customers
    orders = []
    order_items = []
    payments = []
    reviews = []
    customers = []

    base_date = datetime(2018, 1, 1)

    for i in range(1, order_count + 1):
        order_id = f"order_{i:06d}"
        cust_id = f"cust_{i:06d}"
        cust_uniq_id = f"person_{(i % 2200) + 1:05d}"
        cust_state = random.choice(["SP", "RJ", "MG", "PR", "RS", "BA", "SC", "DF", "PE"])

        customers.append({
            "customer_id": cust_id,
            "customer_unique_id": cust_uniq_id,
            "customer_zip_code_prefix": f"{random.randint(10000, 99999)}",
            "customer_city": "City_" + cust_state,
            "customer_state": cust_state,
        })

        # Ensure at least 150 orders in August 2018 are late electronics from Southeast
        is_target_spike_order = (i <= 180)

        if is_target_spike_order:
            # Delivered in August 2018, late
            purchase_dt = datetime(2018, 7, random.randint(15, 28), random.randint(8, 20))
            approved_dt = purchase_dt + timedelta(hours=2)
            # Carrier handoff: some late, some on-time
            handoff_late = (i % 2 == 0)
            shipping_limit_dt = purchase_dt + timedelta(days=4)
            carrier_dt = shipping_limit_dt + timedelta(days=2 if handoff_late else -1)
            estimated_dt = purchase_dt + timedelta(days=12)
            # Delivered late in August 2018
            delay_days = random.randint(7, 22)
            delivered_dt = estimated_dt + timedelta(days=delay_days)
            # Ensure delivered in August
            if delivered_dt.month != 8 or delivered_dt.year != 2018:
                delivered_dt = datetime(2018, 8, random.randint(10, 28))
                delay_days = (delivered_dt.date() - estimated_dt.date()).days
            status = "delivered"
        else:
            # General distribution over 2017-2018
            days_offset = random.randint(0, 580)
            purchase_dt = base_date + timedelta(days=days_offset)
            approved_dt = purchase_dt + timedelta(hours=random.randint(1, 24))
            shipping_limit_dt = purchase_dt + timedelta(days=random.randint(3, 7))
            status = "delivered" if random.random() < 0.94 else "canceled"
            if status == "delivered":
                carrier_dt = purchase_dt + timedelta(days=random.randint(2, 5))
                estimated_dt = purchase_dt + timedelta(days=random.randint(10, 25))
                is_late_flag = random.random() < 0.12
                delay_days = random.randint(2, 18) if is_late_flag else random.randint(-10, -1)
                delivered_dt = estimated_dt + timedelta(days=delay_days)
            else:
                carrier_dt = None
                delivered_dt = None
                estimated_dt = purchase_dt + timedelta(days=15)
                delay_days = None

        orders.append({
            "order_id": order_id,
            "customer_id": cust_id,
            "order_status": status,
            "order_purchase_timestamp": purchase_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "order_approved_at": approved_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "order_delivered_carrier_date": carrier_dt.strftime("%Y-%m-%d %H:%M:%S") if carrier_dt else "",
            "order_delivered_customer_date": delivered_dt.strftime("%Y-%m-%d %H:%M:%S") if delivered_dt else "",
            "order_estimated_delivery_date": estimated_dt.strftime("%Y-%m-%d %H:%M:%S"),
        })

        # Items (1 to 3 items)
        item_count = 1 if not is_target_spike_order and random.random() < 0.8 else random.randint(1, 2)
        order_total_price = 0.0
        order_total_freight = 0.0

        for item_seq in range(1, item_count + 1):
            if is_target_spike_order:
                # Electronics product, Southeast seller
                prod = random.choice([p for p in products if p["product_category_name"] in ("eletronicos", "informatica_acessorios", "telefonia")])
                seller = random.choice([s for s in sellers if s["seller_state"] in ("SP", "RJ", "MG")])
            else:
                prod = random.choice(products)
                seller = random.choice(sellers)

            price = round(random.uniform(25.0, 350.0), 2)
            freight = round(random.uniform(12.0, 45.0), 2)
            order_total_price += price
            order_total_freight += freight

            order_items.append({
                "order_id": order_id,
                "order_item_id": item_seq,
                "product_id": prod["product_id"],
                "seller_id": seller["seller_id"],
                "shipping_limit_date": shipping_limit_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "price": f"{price:.2f}",
                "freight_value": f"{freight:.2f}",
            })

        # Payments
        total_payment = round(order_total_price + order_total_freight, 2)
        payments.append({
            "order_id": order_id,
            "payment_sequential": 1,
            "payment_type": random.choice(["credit_card", "credit_card", "boleto", "debit_card"]),
            "payment_installments": random.choice([1, 1, 2, 3, 6, 10]),
            "payment_value": f"{total_payment:.2f}",
        })

        # Reviews
        if status == "delivered":
            score = 1 if (delay_days and delay_days >= 7) else (5 if random.random() < 0.75 else random.randint(2, 4))
            reviews.append({
                "review_id": f"rev_{i:06d}",
                "order_id": order_id,
                "review_score": score,
                "review_comment_title": "Atraso na entrega" if score <= 2 else "Muito bom",
                "review_comment_message": "Produto demorou mais de duas semanas para chegar." if score <= 2 else "Entrega rapida e produto conforme anunciado.",
                "review_creation_date": delivered_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "review_answer_timestamp": (delivered_dt + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
            })

    # Write gzipped CSVs
    files_to_write = [
        ("olist_orders_dataset.csv.gz", orders),
        ("olist_order_items_dataset.csv.gz", order_items),
        ("olist_order_payments_dataset.csv.gz", payments),
        ("olist_order_reviews_dataset.csv.gz", reviews),
        ("olist_customers_dataset.csv.gz", customers),
        ("olist_sellers_dataset.csv.gz", sellers),
        ("olist_products_dataset.csv.gz", products),
        ("product_category_name_translation.csv.gz", translations),
    ]

    for fname, data_rows in files_to_write:
        out_path = SAMPLE_DIR / fname
        if not data_rows:
            continue
        fieldnames = list(data_rows[0].keys())
        with gzip.open(out_path, "wt", encoding="utf-8", newline="") as gz_file:
            writer = csv.DictWriter(gz_file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data_rows)
        print(f"Created {out_path} ({len(data_rows)} rows)")


if __name__ == "__main__":
    generate_synthetic_sample()
