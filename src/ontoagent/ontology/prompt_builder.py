"""Ontology-driven prompt generation for SQL and Cypher specialists.

Purpose:
    Generates deterministic, role-filtered schema definitions, join pitfalls,
    and business metric definitions directly from ontology.yaml.
    Prevents the LLM from hallucinating or referencing unauthorized columns.
"""

from typing import List, Optional
from ontoagent.ontology.models import GlossaryEntry, Ontology
from ontoagent.ontology.time import DateRange
from ontoagent.guards.rbac import get_role_policy


def render_sql_schema_prompt(
    onto: Ontology,
    role: str = "analyst",
    resolved_time: Optional[DateRange] = None,
    matched_glossary: Optional[List[GlossaryEntry]] = None,
) -> str:
    """Render deterministic, role-filtered SQL schema documentation.

    Args:
        onto: Loaded domain ontology.
        role: Caller role ('analyst' or 'ops_manager').
        resolved_time: Optional resolved DateRange fact.
        matched_glossary: Optional resolved business glossary terms.

    Returns:
        Structured markdown string containing allowed schema, grain, pitfalls, and facts.
    """
    policy = get_role_policy(role)
    allowed_tables = set(policy.allowed_tables)
    denied_columns = set(policy.denied_columns)

    lines: List[str] = [
        "### AVAILABLE DATABASE SCHEMAS (PostgreSQL - Schema 'analytics')",
        "Only query the tables and columns listed below. Always schema-qualify table names (e.g., analytics.fct_orders).",
        "",
    ]

    # Deterministically sort entities
    for entity_name in sorted(onto.entities.keys()):
        entity = onto.entities[entity_name]
        table = entity.sql_table
        if not table or table not in allowed_tables:
            continue

        lines.append(f"Table: {table}")
        if entity.grain:
            lines.append(f"Grain: {entity.grain}")
        if entity.description:
            lines.append(f"Description: {entity.description}")
        lines.append("Columns:")

        # Sort properties deterministically
        for prop_name in sorted(entity.properties.keys()):
            prop = entity.properties[prop_name]
            full_col_name = f"{table}.{prop_name}"
            if full_col_name in denied_columns:
                continue

            null_desc = "NULLABLE" if prop.nullable else "NOT NULL"
            enum_desc = f", ENUM: {prop.values}" if prop.values else ""
            desc = f" -- {prop.description}" if prop.description else ""
            lines.append(f"  - {prop_name} ({prop.type}, {null_desc}{enum_desc}){desc}")

        lines.append("")

    # Join pitfalls
    if onto.join_pitfalls:
        lines.append("### CRITICAL JOIN PITFALLS:")
        for pitfall in onto.join_pitfalls:
            lines.append(f"- {pitfall}")
        lines.append("")

    # Resolved time context
    if resolved_time:
        lines.append("### RESOLVED TIME FACT:")
        lines.append(f"- {resolved_time.to_fact_string()}")
        lines.append("")

    # Matched glossary terms
    if matched_glossary:
        lines.append("### RESOLVED BUSINESS TERMS:")
        for entry in matched_glossary:
            term_str = entry.term if isinstance(entry.term, str) else ", ".join(entry.term)
            lines.append(f"- '{term_str}' resolves to: {entry.resolves_to}")
            if entry.note:
                lines.append(f"  Note: {entry.note}")
        lines.append("")

    return "\n".join(lines)


def render_cypher_schema_prompt(onto: Ontology, role: str = "analyst") -> str:
    """Render deterministic Cypher graph schema documentation."""
    lines: List[str] = [
        "### AVAILABLE GRAPH SCHEMA (Neo4j)",
        "Nodes and Properties:",
    ]

    for entity_name in sorted(onto.entities.keys()):
        entity = onto.entities[entity_name]
        label = entity.graph_label
        if not label:
            continue
        props = [p for p in sorted(entity.properties.keys()) if entity.properties[p].sensitivity != "pii"]
        lines.append(f"- (:{label} {{{', '.join(props)}}})")

    lines.append("")
    lines.append("Relationships:")
    for rel in onto.relationships:
        from_str = rel.from_ if isinstance(rel.from_, str) else "|".join(rel.from_)
        props_str = f" {{{', '.join(rel.properties)}}}" if rel.properties else ""
        lines.append(f"- ({from_str})-[:{rel.name}{props_str}]->({rel.to})")

    lines.append("")
    return "\n".join(lines)
