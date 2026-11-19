"""Cypher query validator for Neo4j operations.

Purpose:
    Validates read-only Cypher queries (Threat T5).
    Strips comments and masks string literals before applying strict keyword blocklists.
    Enforces starting clauses, entity label allowlists, and injects/clamps LIMIT <= 500.
"""

from dataclasses import dataclass, field
import re
from typing import List, Optional
from ontoagent.ontology.models import Ontology


@dataclass
class CypherValidationResult:
    """Outcome of Cypher validation."""
    ok: bool
    code: str
    reasons: List[str] = field(default_factory=list)
    rewritten_cypher: Optional[str] = None


MUTATION_KEYWORDS = [
    r"\bCREATE\b", r"\bMERGE\b", r"\bDELETE\b", r"\bDETACH\b",
    r"\bSET\b", r"\bREMOVE\b", r"\bDROP\b", r"\bLOAD\s+CSV\b",
    r"\bFOREACH\b", r"\bCALL\b", r"\bUSING\s+PERIODIC\s+COMMIT\b"
]


def mask_string_literals(cypher: str) -> str:
    """Replace string literal contents with neutral placeholders to prevent false positives."""
    # Match '...' or "..." literals handling escapes
    return re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", "'__STR__'", cypher)


def validate_cypher(cypher: str, onto: Optional[Ontology] = None) -> CypherValidationResult:
    """Validate and rewrite Cypher query for read-only execution.

    Args:
        cypher: Raw Cypher query string.
        onto: Optional domain ontology containing allowed node labels.

    Returns:
        CypherValidationResult with sanitized rewritten_cypher when valid.
    """
    if not cypher or not cypher.strip():
        return CypherValidationResult(ok=False, code="SYNTAX_ERROR", reasons=["Empty Cypher query"])

    # Clean markdown
    cleaned = re.sub(r"^```(?:cypher)?\s*", "", cypher.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())

    # Strip single-line and multi-line comments
    no_comments = re.sub(r"//[^\n]*", "", cleaned)
    no_comments = re.sub(r"/\*[\s\S]*?\*/", "", no_comments).strip()

    # Mask string literals for keyword check
    masked = mask_string_literals(no_comments)

    # 1. Multi-statement check
    if ";" in masked.rstrip(";"):
        return CypherValidationResult(
            ok=False,
            code="SEC_MULTI_STATEMENT",
            reasons=["Multiple Cypher statements separated by semicolon are forbidden"]
        )

    # 2. Reject mutation keywords and procedure calls
    for kw_pattern in MUTATION_KEYWORDS:
        if re.search(kw_pattern, masked, re.IGNORECASE):
            match_word = re.search(kw_pattern, masked, re.IGNORECASE).group(0)
            return CypherValidationResult(
                ok=False,
                code="SEC_NOT_READ_ONLY",
                reasons=[f"Mutation keyword or procedure call '{match_word}' is forbidden"]
            )

    # 3. Starting clause check
    start_match = re.match(r"^\s*(MATCH|OPTIONAL\s+MATCH|WITH|UNWIND|RETURN)\b", masked, re.IGNORECASE)
    if not start_match:
        return CypherValidationResult(
            ok=False,
            code="SEC_INVALID_START",
            reasons=["Cypher queries must begin with MATCH, OPTIONAL MATCH, WITH, UNWIND, or RETURN"]
        )

    # 4. Label allowlist check (if ontology provided)
    if onto:
        allowed_labels = {
            entity.graph_label for entity in onto.entities.values() if entity.graph_label
        }
        # Find node labels like (:Label) or (n:Label) and relationship types like [:REL]
        node_labels = re.findall(r"\([A-Za-z0-9_]*:\s*([A-Za-z0-9_]+)", masked)
        rel_types = re.findall(r"\[[A-Za-z0-9_]*:\s*([A-Za-z0-9_]+)", masked)
        for label in node_labels:
            if label not in allowed_labels:
                return CypherValidationResult(
                    ok=False,
                    code="UNKNOWN_LABEL",
                    reasons=[f"Label '{label}' is not defined in ontology"]
                )
        for rel in rel_types:
            if not any(r.name == rel for r in onto.relationships):
                return CypherValidationResult(
                    ok=False,
                    code="UNKNOWN_LABEL",
                    reasons=[f"Relationship '{rel}' is not defined in ontology"]
                )

    # 5. Inject or clamp LIMIT <= 500
    rewritten = no_comments.rstrip(";")
    limit_match = re.search(r"\bLIMIT\s+(\d+)\b", rewritten, re.IGNORECASE)
    if limit_match:
        limit_val = int(limit_match.group(1))
        if limit_val > 500:
            rewritten = re.sub(r"\bLIMIT\s+\d+\b", "LIMIT 500", rewritten, flags=re.IGNORECASE)
    else:
        rewritten = f"{rewritten}\nLIMIT 500"

    return CypherValidationResult(ok=True, code="OK", rewritten_cypher=rewritten)
