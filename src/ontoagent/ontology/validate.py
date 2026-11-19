"""Startup ontology consistency validator.

Purpose:
    Ensures ontology definitions, entity relationships, glossary mappings,
    and RBAC privacy policies remain strictly synchronized.
"""

from typing import List, Optional
from ontoagent.errors import ValidationError
from ontoagent.guards.rbac import load_rbac_policies
from ontoagent.ontology.models import Ontology


def validate_ontology(onto: Ontology, strict: bool = True) -> List[str]:
    """Validate ontology consistency and security invariants.

    Args:
        onto: Loaded ontology object.
        strict: If True, raises ValidationError on any error.

    Returns:
        List of error descriptions.
    """
    errors: List[str] = []
    entities = onto.entities

    # 1. Validate relationship endpoints
    for rel in onto.relationships:
        from_nodes = [rel.from_] if isinstance(rel.from_, str) else rel.from_
        for fn in from_nodes:
            if fn not in entities:
                errors.append(f"Relationship '{rel.name}' from-endpoint '{fn}' is not a defined entity.")
        if rel.to not in entities:
            errors.append(f"Relationship '{rel.name}' to-endpoint '{rel.to}' is not a defined entity.")

    # 2. Validate glossary targets
    known_columns = set()
    for ent in entities.values():
        for prop in ent.properties.keys():
            known_columns.add(prop.lower())

    for entry in onto.glossary:
        # Check if resolves_to mentions known column or valid predicate
        resolves = entry.resolves_to.lower()
        if not any(col in resolves for col in known_columns) and "days" not in resolves:
            errors.append(f"Glossary term '{entry.term}' resolves to unknown column reference: '{entry.resolves_to}'")

    # 3. Security invariant: PII & free_text columns must have masking or denial in RBAC
    rbac = load_rbac_policies()
    analyst_policy = rbac.get("analyst")
    if analyst_policy:
        for ent_name, ent in entities.items():
            tbl = ent.sql_table or ""
            for prop_name, prop in ent.properties.items():
                if prop.sensitivity in ("pii", "free_text"):
                    full_name = f"{tbl}.{prop_name}"
                    # Table must either be denied or the column explicitly denied/masked
                    if tbl in analyst_policy.allowed_tables and full_name not in analyst_policy.denied_columns:
                        errors.append(
                            f"Sensitive column '{full_name}' ({prop.sensitivity}) is accessible to analyst role."
                        )

    if errors and strict:
        raise ValidationError(
            f"Ontology validation failed with {len(errors)} error(s):\n" + "\n".join(errors)
        )

    return errors
