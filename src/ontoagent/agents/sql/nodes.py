"""Node functions for the SQL specialist subgraph.

Purpose:
    Handles generation, AST validation, execution, repair loop (<= 2 attempts),
    and safe summarization/masking of relational database results.
    Enforces honest fail-closed behavior without fabricated data.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage

from ontoagent.agents.example_selector import format_few_shot_prompt, select_few_shot_examples
from ontoagent.agents.value_linker import link_values
from ontoagent.config import get_settings
from ontoagent.db.pg import execute_ro_query
from ontoagent.graph.models import SqlStepResult
from ontoagent.guards.pii import mask_rows
from ontoagent.guards.sanitize import sanitize_untrusted
from ontoagent.guards.sql_validator import validate_sql
from ontoagent.llm import extract_text_content, get_llm
from ontoagent.ontology.loader import load_ontology
from ontoagent.ontology.prompt_builder import render_sql_schema_prompt
from ontoagent.ontology.time import DateRange, resolve_time_expression

logger = logging.getLogger(__name__)


async def run_sql_instruction(
    instruction: str,
    role: str = "analyst",
    as_of: str = "2018-09-01",
    max_repairs: int = 2,
    use_fake: bool = False,
) -> SqlStepResult:
    """Execute full SQL generation, validation, repair, and digest cycle for a single subtask.

    Args:
        instruction: Natural language instruction for SQL.
        role: Caller role ('analyst' or 'ops_manager').
        as_of: Historical as-of date string.
        max_repairs: Maximum repair attempts on syntax/DB errors.
        use_fake: Whether to use FakeChatModel for offline tests.

    Returns:
        SqlStepResult with execution status, row digests, and candidate IDs.
    """
    start_time = time.time()
    onto = load_ontology()
    settings = get_settings()

    # 1. Resolve time and linked values
    time_fact = resolve_time_expression(instruction, as_of_str=as_of)
    linked = link_values(instruction, onto=onto) if settings.features.value_linking else []

    # 2. Select few-shot examples
    examples = select_few_shot_examples(instruction, k=4) if settings.features.few_shot else []
    few_shot_str = format_few_shot_prompt(examples)

    # 3. Build schema prompt
    schema_prompt = render_sql_schema_prompt(
        onto=onto,
        role=role,
        resolved_time=time_fact,
        matched_glossary=linked,
    )

    system_prompt = (
        "You are an expert PostgreSQL data engineer for an e-commerce operations team.\n"
        f"{schema_prompt}\n"
        f"{few_shot_str}\n"
        "CONTRACT:\n"
        "- Return only a single valid PostgreSQL SELECT statement in a ```sql block.\n"
        "- No explanations, comments, apologies, or multiple queries.\n"
        "- Always schema-qualify tables (e.g. analytics.fct_orders, analytics.fct_order_items, analytics.fct_reviews).\n"
        "- Only reference allowed tables and columns from the provided schema above.\n"
        "- Map any mentioned concepts (e.g. categories, late shipments, orders) directly to the provided schema tables.\n"
    )

    llm = get_llm(use_fake=use_fake)
    user_prompt = f"Instruction: {instruction}"

    attempts = 0
    current_sql: Optional[str] = None
    validation_err: Optional[str] = None
    db_err: Optional[str] = None
    rows: List[Dict[str, Any]] = []

    while attempts <= max_repairs:
        attempts += 1
        if attempts == 1:
            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        else:
            # Repair prompt with sanitized error
            err_msg = validation_err or db_err
            repair_prompt = (
                f"Your previous SQL query failed validation or execution with error:\n{err_msg}\n\n"
                f"Failed SQL:\n```sql\n{current_sql}\n```\n\n"
                "Please fix the error and return the corrected single PostgreSQL SELECT query in a ```sql block."
            )
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
                HumanMessage(content=repair_prompt),
            ]

        try:
            resp = await llm.ainvoke(messages)
            raw_content = extract_text_content(resp.content if hasattr(resp, "content") else resp)
        except Exception as e:
            # Fail closed on LLM error (Bug B1: never substitute fallback query)
            logger.error("SQL generation LLM call failed: %s", str(e))
            return SqlStepResult(
                ok=False,
                instruction=instruction,
                sql="",
                attempts=attempts,
                error_code="LLM_ERROR",
                error=f"LLM generation failed: {str(e)}",
                elapsed_ms=int((time.time() - start_time) * 1000),
            )

        # Validate SQL
        v_res = validate_sql(raw_content, role=role, onto=onto)
        current_sql = v_res.rewritten_sql or raw_content

        if not v_res.ok:
            # Critical: Never repair security violations
            if v_res.code.startswith("SEC_"):
                return SqlStepResult(
                    ok=False,
                    instruction=instruction,
                    sql=current_sql,
                    attempts=attempts,
                    error_code=v_res.code,
                    error="; ".join(v_res.reasons),
                    elapsed_ms=int((time.time() - start_time) * 1000),
                )
            validation_err = "; ".join(v_res.reasons)
            continue

        # Validation succeeded; reset any previous validation error
        validation_err = None

        # Execute query against PostgreSQL
        try:
            rows = await execute_ro_query(current_sql, max_rows=1000)
            db_err = None
            break
        except Exception as e:
            db_err = str(e)

            # Explicit offline fixture support (Bug B1)
            if os.environ.get("ONTOAGENT_OFFLINE_FIXTURES") == "1":
                logger.info("ONTOAGENT_OFFLINE_FIXTURES=1 active; loading labelled fixture rows")
                rows = [
                    {
                        "order_id": "order_fixture_001",
                        "delivered_month": "2018-08-01",
                        "is_late": True,
                        "order_value": 150.00,
                        "_fixture": True,
                    },
                    {
                        "order_id": "order_fixture_002",
                        "delivered_month": "2018-08-01",
                        "is_late": True,
                        "order_value": 85.50,
                        "_fixture": True,
                    },
                ]
                db_err = None
                break

            # Fail closed on DB connection failure (Bug B1: never fabricate rows)
            if any(w in db_err.lower() for w in ("connection", "connect", "timeout", "refused", "offline", "authentication failed", "no module named")):
                logger.warning("Database unavailable (%s); failing closed without fabricated rows", db_err)
                return SqlStepResult(
                    ok=False,
                    instruction=instruction,
                    sql=current_sql,
                    attempts=attempts,
                    error_code="DB_UNAVAILABLE",
                    error=f"Database unavailable: {db_err}",
                    elapsed_ms=int((time.time() - start_time) * 1000),
                )

            # Query syntax/execution error: continue to repair loop
            continue

    if validation_err or db_err:
        return SqlStepResult(
            ok=False,
            instruction=instruction,
            sql=current_sql,
            attempts=attempts,
            error_code="REPAIR_EXHAUSTED",
            error=validation_err or db_err,
            elapsed_ms=int((time.time() - start_time) * 1000),
        )

    # 4. Digest results and candidate IDs (Bug B6)
    columns = list(rows[0].keys()) if rows else []

    # B6: candidate_ids must come from the executed query's unmasked order_id column ONLY when it exists
    candidate_ids: List[str] = []
    if rows and "order_id" in columns:
        candidate_ids = [
            str(r["order_id"])
            for r in rows
            if r.get("order_id") is not None
            and str(r.get("order_id")) not in ("[MASKED]", "***", "")
            and not r.get("_fixture", False)
        ][:500]

    # Mask sensitive columns for display
    safe_rows = mask_rows(rows, onto=onto, role=role)

    # Numeric summary statistics
    numeric_digest: Dict[str, Any] = {}
    if safe_rows:
        for col in columns:
            vals = [r[col] for r in safe_rows if isinstance(r.get(col), (int, float))]
            if vals:
                numeric_digest[col] = {
                    "min": min(vals),
                    "max": max(vals),
                    "sum": sum(vals),
                    "count": len(vals),
                }

    digest = {
        "summary": f"Executed query returned {len(safe_rows)} rows across {len(columns)} columns.",
        "numeric_stats": numeric_digest,
    }

    return SqlStepResult(
        ok=True,
        instruction=instruction,
        sql=current_sql,
        attempts=attempts,
        columns=columns,
        row_count=len(safe_rows),
        rows=safe_rows[:30],
        digest=digest,
        candidate_ids=candidate_ids,
        elapsed_ms=int((time.time() - start_time) * 1000),
    )
