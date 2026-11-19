"""Value linker and glossary phrase resolver.

Purpose:
    Normalizes natural language entities (states, categories, regions) to canonical values.
    Matches ontology glossary definitions and applies rapidfuzz string similarity (score >= 88).
"""

from typing import Dict, List, Optional, Tuple
from rapidfuzz import fuzz, process
from ontoagent.ontology.models import GlossaryEntry, Ontology

# Standard allowed distinct values
KNOWN_DISTINCT_VALUES = {
    "seller_region": ["North", "Northeast", "Center-West", "Southeast", "South"],
    "customer_region": ["North", "Northeast", "Center-West", "Southeast", "South"],
    "order_status": ["delivered", "shipped", "canceled", "unavailable", "invoiced", "processing", "created", "approved"],
    "category_group": ["electronics", "home_furniture", "health_beauty", "sports_leisure", "fashion", "auto", "other"],
    "payment_type": ["credit_card", "boleto", "voucher", "debit_card"],
    "state": ["SP", "RJ", "MG", "PR", "SC", "RS", "BA", "DF", "PE", "CE", "ES", "GO"],
}


def link_values(text: str, onto: Ontology, score_cutoff: float = 88.0) -> List[GlossaryEntry]:
    """Identify business terms in text and resolve to canonical SQL conditions.

    Args:
        text: User question text.
        onto: Loaded domain ontology.
        score_cutoff: Minimum RapidFuzz match ratio (default 88).

    Returns:
        List of matched GlossaryEntry objects with resolved expressions.
    """
    if not text:
        return []

    lower_text = text.lower()
    matched_entries: List[GlossaryEntry] = []
    already_resolved = set()

    # 1. Exact or substring match ontology glossary entries
    for entry in onto.glossary:
        terms = [entry.term] if isinstance(entry.term, str) else entry.term
        for term in terms:
            if term.lower() in lower_text:
                if entry.resolves_to not in already_resolved:
                    matched_entries.append(entry)
                    already_resolved.add(entry.resolves_to)
                break

    # 2. Fuzzy match distinct domain values
    words = lower_text.split()
    for col_name, candidates in KNOWN_DISTINCT_VALUES.items():
        for candidate in candidates:
            # Check exact match first
            if candidate.lower() in lower_text:
                resolves = f"{col_name} = '{candidate}'"
                if resolves not in already_resolved:
                    matched_entries.append(GlossaryEntry(
                        term=candidate,
                        resolves_to=resolves,
                        note="Matched from known distinct values"
                    ))
                    already_resolved.add(resolves)
                continue

            # Fuzzy match with token chunks
            match = process.extractOne(candidate.lower(), words, scorer=fuzz.ratio, score_cutoff=score_cutoff)
            if match:
                resolves = f"{col_name} = '{candidate}'"
                if resolves not in already_resolved:
                    matched_entries.append(GlossaryEntry(
                        term=match[0],
                        resolves_to=resolves,
                        note=f"Fuzzy match (score: {match[1]:.0f})"
                    ))
                    already_resolved.add(resolves)

    return matched_entries
