"""Node functions for the Graph specialist subgraph.

Purpose:
    Handles Cypher generation from ontology and parameterized patterns,
    AST safety validation via cypher_validator, syntax repair loop,
    and async execution against Neo4j.
"""

import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional
import yaml

from langchain_core.messages import HumanMessage, SystemMessage
from neo4j import AsyncGraphDatabase

from ontoagent.config import get_settings
from ontoagent.graph.models import GraphStepResult
from ontoagent.guards.cypher_validator import validate_cypher
from ontoagent.llm import extract_text_content, get_llm
from ontoagent.ontology.loader import load_ontology
from ontoagent.ontology.models import Ontology

logger = logging.getLogger(__name__)

PATTERNS_PATH = Path("ontology/cypher_patterns.yaml")


def load_cypher_patterns() -> List[Dict[str, Any]]:
    """Load parameterized patterns from ontology/cypher_patterns.yaml."""
    if not PATTERNS_PATH.exists():
        for parent in Path(__file__).resolve().parents:
            cand = parent / "ontology" / "cypher_patterns.yaml"
            if cand.exists():
                with open(cand, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    return data.get("patterns", [])
        return []
    with open(PATTERNS_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        return data.get("patterns", [])


def format_cypher_patterns_prompt(patterns: List[Dict[str, Any]]) -> str:
    """Format patterns into few-shot guidance for Cypher LLM."""
    if not patterns:
        return ""
    lines = ["CANONICAL GRAPH PATTERNS:"]
    for p in patterns[:6]:
        lines.append(f"Pattern: {p.get('name')}")
        lines.append(f"Intent: {p.get('intent')}")
        lines.append(f"Example Question: {p.get('example_question')}")
        lines.append(f"Cypher:\n```cypher\n{p.get('cypher', '').strip()}\n```\n")
    return "\n".join(lines)


async def run_graph_instruction(
    instruction: str,
    onto: Optional[Ontology] = None,
    use_fake: bool = False,
    max_repairs: int = 2,
) -> GraphStepResult:
    """Execute Cypher generation, safety validation, repair, and Neo4j execution for a subtask.

    Args:
        instruction: Natural language query for graph topology.
        onto: Domain ontology schema.
        use_fake: Whether to use FakeChatModel for offline tests.
        max_repairs: Maximum syntax repair attempts.

    Returns:
        GraphStepResult with execution status, Cypher query, and returned rows.
    """
    start_time = time.time()
    onto = onto or load_ontology()
    settings = get_settings()

    patterns = load_cypher_patterns()
    patterns_prompt = format_cypher_patterns_prompt(patterns)

    # Format allowed entities and relationships
    labels = list(onto.entities.keys())
    rels = [f"(:{r.from_})-[:{r.name}]->(:{r.to})" for r in onto.relationships]

    system_prompt = (
        "You are an expert Neo4j Cypher engineer for an e-commerce marketplace operations platform.\n"
        f"Available Node Labels: {', '.join(labels)}\n"
        f"Available Relationships: {', '.join(rels)}\n\n"
        f"{patterns_prompt}\n"
        "CONTRACT:\n"
        "- Return only a single valid Neo4j Cypher read-only query in a ```cypher block.\n"
        "- Read-only queries only (MATCH / WITH / RETURN / ORDER BY / LIMIT).\n"
        "- Never use mutation keywords (CREATE, MERGE, DELETE, SET, REMOVE, DROP).\n"
        "- Always include LIMIT <= 100 on unbounded traversals.\n"
    )

    llm = get_llm(use_fake=use_fake)
    user_prompt = f"Instruction: {instruction}"

    attempts = 0
    current_cypher: Optional[str] = None
    validation_err: Optional[str] = None
    db_err: Optional[str] = None
    rows: List[Dict[str, Any]] = []

    while attempts <= max_repairs:
        attempts += 1
        if attempts == 1:
            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        else:
            err_msg = validation_err or db_err
            repair_prompt = (
                f"Your previous Cypher query failed validation or execution with error:\n{err_msg}\n\n"
                f"Failed Cypher:\n```cypher\n{current_cypher}\n```\n\n"
                "Please fix the error and return the corrected single read-only Cypher query in a ```cypher block."
            )
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
                HumanMessage(content=repair_prompt),
            ]

        try:
            resp = await llm.ainvoke(messages)
            raw_text = extract_text_content(resp.content if hasattr(resp, "content") else resp)
        except Exception as e:
            return GraphStepResult(
                ok=False,
                instruction=instruction,
                cypher=None,
                attempts=attempts,
                error_code="LLM_FAILURE",
                error=f"Cypher generation failed: {str(e)}",
                elapsed_ms=int((time.time() - start_time) * 1000),
            )

        # Extract Cypher from code block
        match = re.search(r"```(?:cypher)?\s*([\s\S]*?)\s*```", raw_text, re.IGNORECASE)
        current_cypher = match.group(1).strip() if match else raw_text.strip()

        # Validate Cypher query
        val_res = validate_cypher(current_cypher, onto=onto)
        if not val_res.ok:
            if val_res.code.startswith("SEC_"):
                # Immediate fail-closed on security violations
                return GraphStepResult(
                    ok=False,
                    instruction=instruction,
                    cypher=current_cypher,
                    attempts=attempts,
                    error_code=val_res.code,
                    error=f"Security violation: {'; '.join(val_res.reasons)}",
                    elapsed_ms=int((time.time() - start_time) * 1000),
                )
            validation_err = f"Validation failed ({val_res.code}): {'; '.join(val_res.reasons)}"
            continue

        validated_cypher = val_res.rewritten_cypher or current_cypher

        # Execute against Neo4j
        try:
            driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
                connection_timeout=3.0,
            )
            async with driver:
                async with driver.session() as session:
                    res_cursor = await session.run(validated_cypher)
                    raw_records = await res_cursor.data()
                    rows = list(raw_records)

            return GraphStepResult(
                ok=True,
                instruction=instruction,
                cypher=validated_cypher,
                attempts=attempts,
                row_count=len(rows),
                rows=rows,
                error_code=None,
                error=None,
                elapsed_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as e:
            db_err = str(e)
            logger.warning("Neo4j execution error on attempt %d: %s", attempts, db_err)
            if attempts > max_repairs:
                break

    # If exhausted or unreachable: check offline fixtures
    is_offline = (
        getattr(settings, "offline_fixtures", False)
        or os.environ.get("ONTOAGENT_OFFLINE_FIXTURES") == "1"
    )
    if is_offline and validated_cypher:
        return GraphStepResult(
            ok=True,
            instruction=instruction,
            cypher=validated_cypher,
            attempts=attempts,
            row_count=1,
            rows=[{"_fixture": True, "result": "sample_graph_fixture"}],
            error_code=None,
            error=None,
            elapsed_ms=int((time.time() - start_time) * 1000),
        )

    return GraphStepResult(
        ok=False,
        instruction=instruction,
        cypher=current_cypher,
        attempts=attempts,
        row_count=0,
        rows=[],
        error_code="DB_UNAVAILABLE" if "connection" in (db_err or "").lower() else "REPAIR_EXHAUSTED",
        error=f"Neo4j execution failed: {db_err or validation_err}",
        elapsed_ms=int((time.time() - start_time) * 1000),
    )
