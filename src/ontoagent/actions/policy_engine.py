"""Pure deterministic policy engine for order compensation and batch planning.

Purpose:
    Evaluates order facts against machine-readable policy definitions (policies/refund_policy.yaml).
    Calculates exact compensation amounts using Decimal arithmetic with ROUND_HALF_UP.
    Hard invariant: Zero LLM math. Models never choose amounts or override business rules.
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
import uuid
import yaml

DEFAULT_POLICY_PATH = Path("policies/refund_policy.yaml")


@dataclass(frozen=True)
class OrderFacts:
    """Ground truth order facts retrieved deterministically from analytics database."""
    order_id: str
    order_status: str
    is_delivered: bool
    delay_days: Optional[int]
    days_past_estimate_as_of: Optional[int]
    items_total: Decimal
    freight_total: Decimal
    order_value: Decimal
    payment_total: Decimal
    has_open_ticket: bool = False


@dataclass(frozen=True)
class RefundDecision:
    """Deterministic policy evaluation result for a single order."""
    order_id: str
    eligible: bool
    tier: Optional[str]
    kind: Literal["goodwill", "full", "none"]
    amount: Decimal
    reason_code: str
    policy_ref: str
    needs_escalation: bool
    escalation_reason: Optional[str]
    ineligible_reason: Optional[str]


@dataclass
class BatchPlan:
    """Bounded, prioritized batch plan for human-in-the-loop review and execution."""
    batch_id: str
    eligible_orders: List[RefundDecision] = field(default_factory=list)
    excluded_orders: List[Dict[str, Any]] = field(default_factory=list)
    total_amount: Decimal = Decimal("0.00")
    overflow_count: int = 0


def load_policy(policy_path: Optional[Path | str] = None) -> Dict[str, Any]:
    """Load and parse refund policy YAML file."""
    path = Path(policy_path) if policy_path else DEFAULT_POLICY_PATH
    if not path.is_file():
        # Fallback to default constants if file unreadable
        return {
            "tiers": {
                "LATE_7": {"min_delay_days": 7, "max_delay_days": 14, "freight_pct": 1.00, "item_pct": 0.00},
                "LATE_15": {"min_delay_days": 15, "max_delay_days": None, "freight_pct": 1.00, "item_pct": 0.20},
            },
            "caps": {
                "goodwill_cap": 150.00,
                "escalation_order_value_threshold": 500.00,
                "batch_max_orders": 25,
                "batch_max_amount": 2000.00,
            },
            "undelivered": {
                "min_days_past_estimate": 10,
                "refund_type": "full",
                "cap_applicable": False,
            },
            "ineligible_statuses": ["canceled"],
        }
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _quantize_money(amount: Decimal) -> Decimal:
    """Quantize decimal to 2 decimal places with ROUND_HALF_UP."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_compensation(
    f: OrderFacts,
    policy: Optional[Dict[str, Any]] = None,
) -> RefundDecision:
    """Pure, deterministic evaluation of compensation for a single order.

    Rules from policies/refund_policy.yaml:
        - Ineligible statuses (e.g. canceled): 0 refund.
        - Open ticket exists: 0 refund.
        - Delivered orders:
            - delay_days < 7: ineligible.
            - delay_days 7..14: Tier LATE_7 -> 100% freight, 0% item.
            - delay_days >= 15: Tier LATE_15 -> 100% freight + 20% item.
            - Goodwill cap: min(amount, 150.00).
            - Payment total bound: min(amount, payment_total).
        - Undelivered orders:
            - days_past_estimate >= 10: 100% full refund (min(order_value, payment_total)).
              Goodwill cap does NOT apply.
            - days_past_estimate < 10: ineligible (pending delivery).
        - Escalation:
            - Any order with order_value > 500.00 gets needs_escalation=True.
    """
    if policy is None:
        policy = load_policy()

    ineligible_statuses = policy.get("ineligible_statuses", ["canceled"])
    caps = policy.get("caps", {})
    goodwill_cap = Decimal(str(caps.get("goodwill_cap", 150.00)))
    escalation_threshold = Decimal(str(caps.get("escalation_order_value_threshold", 500.00)))

    # Escalation check: order_value > 500.00 requires director review
    needs_escalation = f.order_value > escalation_threshold
    escalation_reason = (
        f"Order value R${f.order_value:.2f} exceeds escalation threshold R${escalation_threshold:.2f}"
        if needs_escalation
        else None
    )

    # Ineligible status check
    if f.order_status in ineligible_statuses:
        return RefundDecision(
            order_id=f.order_id,
            eligible=False,
            tier=None,
            kind="none",
            amount=Decimal("0.00"),
            reason_code="INELIGIBLE_STATUS",
            policy_ref="refund_policy#Ineligible",
            needs_escalation=needs_escalation,
            escalation_reason=escalation_reason,
            ineligible_reason=f"Order status '{f.order_status}' is ineligible for refund",
        )

    # Existing ticket check
    if f.has_open_ticket:
        return RefundDecision(
            order_id=f.order_id,
            eligible=False,
            tier=None,
            kind="none",
            amount=Decimal("0.00"),
            reason_code="OPEN_TICKET_EXISTS",
            policy_ref="refund_policy#Ineligible",
            needs_escalation=needs_escalation,
            escalation_reason=escalation_reason,
            ineligible_reason="Order already has an open or processed refund ticket",
        )

    # Case 1: Delivered orders
    if f.is_delivered:
        delay = f.delay_days if f.delay_days is not None else 0
        if delay < 7:
            return RefundDecision(
                order_id=f.order_id,
                eligible=False,
                tier=None,
                kind="none",
                amount=Decimal("0.00"),
                reason_code="NO_DELAY",
                policy_ref="refund_policy",
                needs_escalation=needs_escalation,
                escalation_reason=escalation_reason,
                ineligible_reason=f"Delivery delay ({delay} days) is under minimum threshold (7 days)",
            )
        elif 7 <= delay <= 14:
            # Tier LATE_7: 100% freight compensation
            tier = "LATE_7"
            raw_amt = f.freight_total
            capped_amt = min(raw_amt, goodwill_cap)
            final_amt = _quantize_money(min(capped_amt, f.payment_total))
            return RefundDecision(
                order_id=f.order_id,
                eligible=final_amt > Decimal("0.00"),
                tier=tier,
                kind="goodwill",
                amount=final_amt,
                reason_code=tier,
                policy_ref="refund_policy#Tier LATE_7",
                needs_escalation=needs_escalation,
                escalation_reason=escalation_reason,
                ineligible_reason=None if final_amt > Decimal("0.00") else "Calculated refund amount is zero",
            )
        else:
            # Tier LATE_15: 100% freight + 20% item value
            tier = "LATE_15"
            raw_amt = f.freight_total + (Decimal("0.20") * f.items_total)
            capped_amt = min(raw_amt, goodwill_cap)
            final_amt = _quantize_money(min(capped_amt, f.payment_total))
            return RefundDecision(
                order_id=f.order_id,
                eligible=final_amt > Decimal("0.00"),
                tier=tier,
                kind="goodwill",
                amount=final_amt,
                reason_code=tier,
                policy_ref="refund_policy#Tier LATE_15",
                needs_escalation=needs_escalation,
                escalation_reason=escalation_reason,
                ineligible_reason=None if final_amt > Decimal("0.00") else "Calculated refund amount is zero",
            )

    # Case 2: Undelivered orders
    undelivered_cfg = policy.get("undelivered", {})
    min_days_past = undelivered_cfg.get("min_days_past_estimate", 10)
    past_est = f.days_past_estimate_as_of if f.days_past_estimate_as_of is not None else 0

    if past_est >= min_days_past:
        # Full refund rule: order_value bounded by payment_total; goodwill cap does not apply
        raw_amt = min(f.order_value, f.payment_total)
        final_amt = _quantize_money(raw_amt)
        return RefundDecision(
            order_id=f.order_id,
            eligible=final_amt > Decimal("0.00"),
            tier=None,
            kind="full",
            amount=final_amt,
            reason_code="UNDELIVERED_10",
            policy_ref="refund_policy#Undelivered",
            needs_escalation=needs_escalation,
            escalation_reason=escalation_reason,
            ineligible_reason=None if final_amt > Decimal("0.00") else "Order value is zero",
        )
    else:
        return RefundDecision(
            order_id=f.order_id,
            eligible=False,
            tier=None,
            kind="none",
            amount=Decimal("0.00"),
            reason_code="UNDELIVERED_PENDING",
            policy_ref="refund_policy#Undelivered",
            needs_escalation=needs_escalation,
            escalation_reason=escalation_reason,
            ineligible_reason=f"Undelivered order is only {past_est} days past estimate (minimum {min_days_past})",
        )


def decide_refund(
    f: OrderFacts,
    policy: Optional[Dict[str, Any]] = None,
) -> RefundDecision:
    """Alias for compute_compensation per policy engine specification."""
    return compute_compensation(f, policy)


def build_batch(
    decisions: List[RefundDecision],
    policy: Optional[Dict[str, Any]] = None,
) -> BatchPlan:
    """Build a prioritized, capped batch plan from individual refund decisions.

    Rules:
        - Escalated orders (order_value > 500) are EXCLUDED from automated batch and listed separately.
        - Ineligible orders are excluded.
        - Batch limits: max 25 orders, max R$2,000.00 total.
        - Candidate orders sorted by amount descending.
        - Orders exceeding batch limits are tracked as overflow.
    """
    if policy is None:
        policy = load_policy()

    caps = policy.get("caps", {})
    batch_max_orders = int(caps.get("batch_max_orders", 25))
    batch_max_amount = Decimal(str(caps.get("batch_max_amount", 2000.00)))

    plan = BatchPlan(batch_id=str(uuid.uuid4()))

    automated_candidates: List[RefundDecision] = []

    for d in decisions:
        if d.needs_escalation:
            plan.excluded_orders.append({
                "order_id": d.order_id,
                "amount": str(d.amount),
                "reason": d.escalation_reason or "Escalation required: order value > R$500.00",
                "tier": d.tier,
                "needs_escalation": True,
            })
        elif not d.eligible:
            plan.excluded_orders.append({
                "order_id": d.order_id,
                "amount": str(d.amount),
                "reason": d.ineligible_reason or "Ineligible",
                "tier": d.tier,
                "needs_escalation": False,
            })
        else:
            automated_candidates.append(d)

    # Sort eligible candidates by severity: largest amount first, then order_id
    automated_candidates.sort(key=lambda x: (x.amount, x.order_id), reverse=True)

    current_total = Decimal("0.00")
    for candidate in automated_candidates:
        if len(plan.eligible_orders) < batch_max_orders and (current_total + candidate.amount <= batch_max_amount):
            plan.eligible_orders.append(candidate)
            current_total += candidate.amount
        else:
            plan.overflow_count += 1
            plan.excluded_orders.append({
                "order_id": candidate.order_id,
                "amount": str(candidate.amount),
                "reason": f"Batch limit exceeded (cap: {batch_max_orders} orders, R${batch_max_amount:.2f})",
                "tier": candidate.tier,
                "needs_escalation": False,
            })

    plan.total_amount = _quantize_money(current_total)
    return plan
