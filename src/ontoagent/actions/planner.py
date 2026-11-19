"""Action planner for operational refund and notification proposals.

Purpose:
    Binds candidate order IDs to verified ground truth facts using fixed, parameterized SQL (ADR-013).
    Executes deterministic policy engine to draft structured ProposedAction plans.
    Strictly enforces authorization gates: ops_manager role only; blocks on hard security flags.
    Never allows LLMs to choose amounts or order IDs.
"""

from decimal import Decimal
import logging
import os
from typing import Any, Dict, List, Optional
import uuid
import psycopg

from ontoagent.actions.policy_engine import (
    BatchPlan,
    OrderFacts,
    build_batch,
    compute_compensation,
)
from ontoagent.config import get_settings

logger = logging.getLogger(__name__)

HARD_RISK_FLAGS = {
    "GUARD_ERROR",
    "ACTION_LANGUAGE_IN_UNTRUSTED",
    "USER_INJECTION_HARD",
}


def fetch_order_facts(
    candidate_order_ids: List[str],
    pg_ro_url: Optional[str] = None,
) -> List[OrderFacts]:
    """Retrieve verified ground-truth order facts using fixed parameterized SQL (ADR-013).

    Args:
        candidate_order_ids: List of unmasked order IDs to evaluate.
        pg_ro_url: Optional PostgreSQL connection URL.

    Returns:
        List of OrderFacts objects.
    """
    if not candidate_order_ids:
        return []

    settings = get_settings()
    ro_url = pg_ro_url or settings.postgres_ro_url
    app_url = settings.postgres_app_url

    facts: List[OrderFacts] = []
    existing_ticket_ids = set()

    # Step 1: Check existing refund tickets in ops schema (via app role)
    try:
        with psycopg.connect(app_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT order_id 
                    FROM ops.refund_tickets 
                    WHERE order_id = ANY(%s) AND status != 'rejected';
                    """,
                    (candidate_order_ids,),
                )
                for (oid,) in cur.fetchall():
                    existing_ticket_ids.add(str(oid))
    except Exception as e:
        logger.warning(f"Could not check ops.refund_tickets: {e}")

    # Step 2: Fetch ground truth facts from analytics.fct_orders (via ro role)
    try:
        with psycopg.connect(ro_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 
                        o.order_id,
                        o.order_status,
                        o.is_delivered,
                        o.delay_days,
                        CASE 
                            WHEN NOT o.is_delivered AND o.estimated_delivery_ts IS NOT NULL 
                            THEN GREATEST(0, EXTRACT(DAY FROM (NOW() - o.estimated_delivery_ts))::int)
                            ELSE 0 
                        END AS days_past_estimate,
                        o.items_total,
                        o.freight_total,
                        o.order_value,
                        o.payment_total
                    FROM analytics.fct_orders o
                    WHERE o.order_id = ANY(%s);
                    """,
                    (candidate_order_ids,),
                )
                for row in cur.fetchall():
                    (
                        order_id,
                        order_status,
                        is_delivered,
                        delay_days,
                        days_past_estimate,
                        items_total,
                        freight_total,
                        order_value,
                        payment_total,
                    ) = row
                    facts.append(
                        OrderFacts(
                            order_id=str(order_id),
                            order_status=str(order_status),
                            is_delivered=bool(is_delivered),
                            delay_days=int(delay_days) if delay_days is not None else None,
                            days_past_estimate_as_of=int(days_past_estimate) if days_past_estimate is not None else None,
                            items_total=Decimal(str(items_total)),
                            freight_total=Decimal(str(freight_total)),
                            order_value=Decimal(str(order_value)),
                            payment_total=Decimal(str(payment_total)),
                            has_open_ticket=str(order_id) in existing_ticket_ids,
                        )
                    )
    except Exception as e:
        logger.error(f"Error executing fixed SQL in fetch_order_facts: {e}")
        # Only fallback if explicit offline fixtures are enabled
        if os.getenv("ONTOAGENT_OFFLINE_FIXTURES") == "1":
            logger.info("Using offline fixture order facts fallback.")
            for oid in candidate_order_ids:
                facts.append(
                    OrderFacts(
                        order_id=oid,
                        order_status="delivered",
                        is_delivered=True,
                        delay_days=10,
                        days_past_estimate_as_of=0,
                        items_total=Decimal("80.00"),
                        freight_total=Decimal("25.00"),
                        order_value=Decimal("105.00"),
                        payment_total=Decimal("105.00"),
                        has_open_ticket=oid in existing_ticket_ids,
                    )
                )

    return facts


def plan_refund_action(
    candidate_order_ids: List[str],
    user_role: str,
    risk_flags: Optional[List[str]] = None,
    thread_id: str = "",
    order_facts_override: Optional[List[OrderFacts]] = None,
) -> Dict[str, Any]:
    """Draft deterministic ProposedAction for candidate order refund compensation.

    Security Invariants:
        1. Role Isolation: ONLY ops_manager can plan or propose actions. Analysts are rejected.
        2. Threat Gating: Hard risk flags immediately abort action planning.
        3. Deterministic Arithmetic: Compensation amounts come purely from policy_engine.

    Returns:
        Structured ProposedAction dictionary.
    """
    risk_flags = risk_flags or []

    # Security Gate 1: Role check
    if user_role != "ops_manager":
        logger.warning(f"Action planning rejected: role '{user_role}' unauthorized (ops_manager required)")
        return {
            "error": "ROLE_FORBIDDEN",
            "items": [],
            "total": "0.00",
            "excluded": [],
            "overflow": 0,
            "rationale": f"Role '{user_role}' is not authorized to plan or execute operational actions.",
        }

    # Security Gate 2: Hard risk flag check
    hit_hard_flags = [f for f in risk_flags if f in HARD_RISK_FLAGS]
    if hit_hard_flags:
        logger.warning(f"Action planning aborted due to security risk flags: {hit_hard_flags}")
        return {
            "error": "SECURITY_GATE_BLOCKED",
            "items": [],
            "total": "0.00",
            "excluded": [],
            "overflow": 0,
            "rationale": f"Action blocked due to security risk flags: {', '.join(hit_hard_flags)}.",
        }

    # Step 1: Fetch order facts (or use override for unit tests)
    facts = order_facts_override if order_facts_override is not None else fetch_order_facts(candidate_order_ids)
    if not facts:
        return {
            "action_id": str(uuid.uuid4()),
            "tool": "create_refund_ticket",
            "items": [],
            "total": "0.00",
            "excluded": [],
            "overflow": 0,
            "rationale": "No order facts matched candidate order IDs in database.",
        }

    # Step 2: Compute policy decisions for each order
    decisions = [compute_compensation(f) for f in facts]

    # Step 3: Build prioritized, bounded batch
    batch: BatchPlan = build_batch(decisions)

    # Step 4: Construct verified ProposedAction payload
    items = [
        {
            "order_id": d.order_id,
            "amount": f"{d.amount:.2f}",
            "reason_code": d.reason_code,
            "policy_ref": d.policy_ref,
        }
        for d in batch.eligible_orders
    ]

    return {
        "action_id": batch.batch_id,
        "tool": "create_refund_ticket",
        "items": items,
        "total": f"{batch.total_amount:.2f}",
        "excluded": batch.excluded_orders,
        "overflow": batch.overflow_count,
        "rationale": (
            f"Deterministic policy engine matched {len(batch.eligible_orders)} eligible order(s) "
            f"totaling R${batch.total_amount:.2f} based on policies/refund_policy.yaml."
        ),
    }
