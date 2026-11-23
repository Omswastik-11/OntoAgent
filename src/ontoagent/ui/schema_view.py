"""Database schema and ontology documentation viewer for the OntoAgent UI.

Purpose:
    Provides interactive schema inspection, entity metadata, Neo4j graph topology,
    canonical business metrics, and category taxonomy search.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ontoagent.ontology.loader import load_category_groups, load_ontology
from ontoagent.ontology.models import EntityDef, Ontology


def get_entities_overview_markdown() -> str:
    """Generate an overview table of all SQL tables and business entities."""
    onto = load_ontology()
    lines = [
        "### 🗄️ Relational Database Schema (`analytics` schema)",
        "",
        "The relational data warehouse is modeled as a star/snowflake schema in PostgreSQL. All analytical queries execute strictly through the read-only role (`ontoagent_ro`).",
        "",
        "| Entity | SQL Table | Primary Key | Granularity | Description |",
        "|---|---|---|---|---|",
    ]

    for name, entity in onto.entities.items():
        if entity.sql_table:
            key_str = f"`{entity.key}`" if entity.key else "-"
            grain_str = entity.grain or "1 row per entity"
            lines.append(
                f"| **{name}** | `{entity.sql_table}` | {key_str} | {grain_str} | {entity.description} |"
            )

    lines.extend([
        "",
        "> [!IMPORTANT]",
        "> **Grain & Fan-Out Warning**: When joining `analytics.fct_orders` with `analytics.fct_order_items`, note that orders contain multiple items. Always aggregate line items or use `COUNT(DISTINCT order_id)` to avoid inflated metrics.",
    ])
    return "\n".join(lines)


def get_entity_detail_markdown(entity_name: str) -> str:
    """Generate detailed column breakdown for a selected entity."""
    onto = load_ontology()
    entity = onto.entities.get(entity_name)
    if not entity:
        return f"Entity `{entity_name}` not found in ontology."

    lines = [
        f"### Entity: **{entity_name}**",
        f"- **SQL Table**: `{entity.sql_table or 'N/A'}`",
        f"- **Graph Label**: `:{entity.graph_label or entity_name}`",
        f"- **Primary Key**: `{entity.key or 'None'}`",
        f"- **Grain**: {entity.grain or 'Unspecified'}",
        f"- **Description**: {entity.description}",
        "",
        "#### Columns & Properties",
        "",
        "| Column Name | Type | Nullable | Sensitivity | Description | Values / Range |",
        "|---|---|---|---|---|---|",
    ]

    for col_name, prop in entity.properties.items():
        null_badge = "Yes" if prop.nullable else "No"
        sens_badge = f"`{prop.sensitivity}`" if prop.sensitivity else "-"
        vals_str = f"`{', '.join(prop.values[:5])}`" if prop.values else (f"Unit: {prop.unit}" if prop.unit else "-")
        desc_str = prop.description or "-"
        lines.append(
            f"| `{col_name}` | `{prop.type}` | {null_badge} | {sens_badge} | {desc_str} | {vals_str} |"
        )

    return "\n".join(lines)


def get_graph_topology_markdown() -> str:
    """Generate markdown describing Neo4j graph nodes and relationships."""
    onto = load_ontology()
    lines = [
        "### 🕸️ Knowledge Graph Topology (Neo4j)",
        "",
        "The graph database captures multi-hop network relationships between customers, orders, items, products, and sellers to uncover co-purchases, fraud clusters, and multi-seller fulfillment.",
        "",
        "#### Graph Node Labels",
        "- `(:Customer)`: Identified by `customer_id` and `customer_unique_id`. Properties: `customer_state`, `customer_region`.",
        "- `(:Order)`: Identified by `order_id`. Properties: `order_status`, `is_late`, `purchase_ts`, `delivered_ts`, `payment_total`.",
        "- `(:Product)`: Identified by `product_id`. Properties: `category_group`, `product_category_name`.",
        "- `(:Seller)`: Identified by `seller_id`. Properties: `seller_state`, `seller_region`.",
        "",
        "#### Directed Relationships",
        "",
        "| Relationship | Pattern | Cardinality | Description |",
        "|---|---|---|---|",
    ]

    for rel in onto.relationships:
        from_node = rel.from_ if isinstance(rel.from_, str) else "/".join(rel.from_)
        lines.append(
            f"| `:{rel.name}` | `(:{from_node})-[:{rel.name}]->(:{rel.to})` | `{rel.cardinality}` | {rel.description or '-'} |"
        )

    lines.extend([
        "",
        "#### Example Cypher Patterns",
        "```cypher\n// 1. Find sellers fulfilling late orders in center-west region\nMATCH (s:Seller)-[:FULFILLS]->(o:Order)\nWHERE o.is_late = true\nRETURN s.seller_id, count(o) AS late_orders\nORDER BY late_orders DESC LIMIT 10;\n```",
        "",
        "```cypher\n// 2. Discover co-purchased product categories\nMATCH (o:Order)-[:CONTAINS]->(p1:Product),\n      (o)-[:CONTAINS]->(p2:Product)\nWHERE p1.product_id < p2.product_id\nRETURN p1.category_group, p2.category_group, count(o) AS shared_orders\nORDER BY shared_orders DESC LIMIT 10;\n```",
    ])
    return "\n".join(lines)


def get_metrics_catalog_markdown() -> str:
    """Generate markdown catalog of standardized business metrics."""
    onto = load_ontology()
    lines = [
        "### 📊 Canonical Business Metrics Dictionary",
        "",
        "These metrics are formally defined in the ontology and used by the SQL specialist to generate verifiable aggregates without formula hallucinations.",
        "",
        "| Metric Name | Description | Base Table | Time Dimension | SQL Formula |",
        "|---|---|---|---|---|",
    ]

    for name, metric in onto.metrics.items():
        table_str = f"`{metric.table}`" if metric.table else "Derived"
        time_str = f"`{metric.default_time_dimension}`" if metric.default_time_dimension else "-"
        sql_str = f"<code>{metric.sql}</code>" if metric.sql else "-"
        lines.append(
            f"| **{name}** | {metric.description} | {table_str} | {time_str} | {sql_str} |"
        )

    lines.extend([
        "",
        "#### Standard Glossary Equivalences",
        "- **\"Late Delivery\"**: Evaluates to `is_late = TRUE` (where `delivered_ts > estimated_delivery_ts`).",
        "- **\"Late Shipment / Handoff\"**: Evaluates to `is_late_handoff = TRUE` (where carrier handoff occurred after `shipping_limit_date`).",
        "- **\"Good Review\"**: Evaluates to `review_score >= 4`.",
        "- **\"Negative / Bad Review\"**: Evaluates to `review_score <= 2`.",
        "- **\"Delivered Orders\"**: Evaluates to `order_status = 'delivered'` and `is_delivered = TRUE`.",
    ])
    return "\n".join(lines)


def get_category_groups_markdown() -> str:
    """Generate markdown breakdown of category taxonomy."""
    groups = load_category_groups()
    lines = [
        "### 🏷️ Standardized Category Taxonomy",
        "",
        "Raw product categories (in Portuguese) are standardized into high-level operational category groups:",
        "",
        "| Category Group | Number of Raw Categories | Example Raw Categories |",
        "|---|---|---|",
    ]

    for group_name, raw_cats in sorted(groups.items()):
        examples = ", ".join(f"`{c}`" for c in raw_cats[:4])
        if len(raw_cats) > 4:
            examples += f" (+{len(raw_cats) - 4} more)"
        lines.append(f"| **{group_name}** | {len(raw_cats)} | {examples} |")

    return "\n".join(lines)


def search_schema(query: str) -> str:
    """Search schema across all tables, columns, and metrics."""
    if not query or not query.strip():
        return get_entities_overview_markdown()

    q = query.strip().lower()
    onto = load_ontology()
    results = [f"### 🔍 Search Results for \"{query}\"", ""]
    matched_any = False

    # 1. Search Tables & Columns
    col_matches = []
    for ent_name, ent in onto.entities.items():
        table_matched = q in ent_name.lower() or (ent.sql_table and q in ent.sql_table.lower()) or (ent.description and q in ent.description.lower())
        for col_name, prop in ent.properties.items():
            desc = prop.description or ""
            if table_matched or q in col_name.lower() or q in desc.lower() or q in prop.type.lower():
                col_matches.append({
                    "entity": ent_name,
                    "table": ent.sql_table or "-",
                    "column": col_name,
                    "type": prop.type,
                    "description": desc,
                })

    if col_matches:
        matched_any = True
        results.append("#### Matching Columns & Attributes")
        results.append("| Entity / Table | Column Name | Type | Description |")
        results.append("|---|---|---|---|")
        for m in col_matches[:25]:
            results.append(f"| **{m['entity']}** (`{m['table']}`) | `{m['column']}` | `{m['type']}` | {m['description']} |")
        if len(col_matches) > 25:
            results.append(f"\n*Showing top 25 of {len(col_matches)} matching columns.*")
        results.append("")

    # 2. Search Metrics
    metric_matches = []
    for m_name, metric in onto.metrics.items():
        if q in m_name.lower() or q in metric.description.lower() or (metric.sql and q in metric.sql.lower()):
            metric_matches.append((m_name, metric))

    if metric_matches:
        matched_any = True
        results.append("#### Matching Business Metrics")
        results.append("| Metric | Formula | Description |")
        results.append("|---|---|---|")
        for m_name, metric in metric_matches:
            results.append(f"| **{m_name}** | <code>{metric.sql or '-'}</code> | {metric.description} |")
        results.append("")

    if not matched_any:
        return f"### 🔍 Search Results for \"{query}\"\n\nNo matching tables, columns, or metrics found. Try terms like `order`, `late`, `freight`, `customer`, `seller`, `price`, or `review`."

    return "\n".join(results)


def get_raw_schema_json() -> str:
    """Return serialized JSON of the entire ontology."""
    onto = load_ontology()
    return json.dumps(onto.model_dump(by_alias=True), indent=2)
