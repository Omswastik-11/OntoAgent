"""Unit tests for the deterministic compensation policy engine.

Verifies exact mathematical compliance, tier boundary edge cases, goodwill caps,
escalation thresholds, batch capping, and deduplication.
"""

from decimal import Decimal
import pytest

from ontoagent.actions.policy_engine import (
    BatchPlan,
    OrderFacts,
    RefundDecision,
    build_batch,
    compute_compensation,
)


def make_order(
    order_id: str = "o1",
    status: str = "delivered",
    is_delivered: bool = True,
    delay_days: int = 10,
    days_past_estimate: int = 0,
    items_total: str = "100.00",
    freight_total: str = "30.00",
    order_value: str = "130.00",
    payment_total: str = "130.00",
    has_open_ticket: bool = False,
) -> OrderFacts:
    return OrderFacts(
        order_id=order_id,
        order_status=status,
        is_delivered=is_delivered,
        delay_days=delay_days,
        days_past_estimate_as_of=days_past_estimate,
        items_total=Decimal(items_total),
        freight_total=Decimal(freight_total),
        order_value=Decimal(order_value),
        payment_total=Decimal(payment_total),
        has_open_ticket=has_open_ticket,
    )


def test_delay_tier_boundary_day_6_vs_day_7():
    """Day 6 delay is ineligible; Day 7 triggers LATE_7 (100% freight)."""
    # Day 6: ineligible
    o6 = make_order(delay_days=6, freight_total="25.50", items_total="100.00")
    d6 = compute_compensation(o6)
    assert not d6.eligible
    assert d6.amount == Decimal("0.00")
    assert d6.reason_code == "NO_DELAY"

    # Day 7: eligible for Tier LATE_7 (100% freight = 25.50)
    o7 = make_order(delay_days=7, freight_total="25.50", items_total="100.00")
    d7 = compute_compensation(o7)
    assert d7.eligible
    assert d7.tier == "LATE_7"
    assert d7.amount == Decimal("25.50")
    assert d7.kind == "goodwill"
    assert d7.policy_ref == "refund_policy#Tier LATE_7"


def test_delay_tier_boundary_day_14_vs_day_15():
    """Day 14 triggers LATE_7; Day 15 triggers LATE_15 (100% freight + 20% item value)."""
    # Day 14: Tier LATE_7 (100% freight only = 30.00)
    o14 = make_order(delay_days=14, freight_total="30.00", items_total="100.00")
    d14 = compute_compensation(o14)
    assert d14.eligible
    assert d14.tier == "LATE_7"
    assert d14.amount == Decimal("30.00")

    # Day 15: Tier LATE_15 (100% freight [30.00] + 20% item [20.00] = 50.00)
    o15 = make_order(delay_days=15, freight_total="30.00", items_total="100.00")
    d15 = compute_compensation(o15)
    assert d15.eligible
    assert d15.tier == "LATE_15"
    assert d15.amount == Decimal("50.00")
    assert d15.policy_ref == "refund_policy#Tier LATE_15"


def test_goodwill_cap_enforced_at_150():
    """Goodwill compensation cannot exceed R$150.00 cap."""
    # Freight R$120 + 20% of R$300 = R$180 -> must be capped at R$150.00
    o = make_order(delay_days=20, freight_total="120.00", items_total="300.00", payment_total="420.00", order_value="420.00")
    d = compute_compensation(o)
    assert d.eligible
    assert d.amount == Decimal("150.00")


def test_bounded_by_payment_total():
    """Goodwill compensation cannot exceed the actual customer payment total."""
    # Freight R$50, but customer only paid R$35 due to vouchers
    o = make_order(delay_days=10, freight_total="50.00", payment_total="35.00", order_value="50.00")
    d = compute_compensation(o)
    assert d.eligible
    assert d.amount == Decimal("35.00")


def test_undelivered_boundary_day_9_vs_day_10():
    """Undelivered order: day 9 past estimate is ineligible; day 10 gets full refund without goodwill cap."""
    # Day 9 past estimate: pending
    u9 = make_order(is_delivered=False, status="shipped", days_past_estimate=9, order_value="250.00", payment_total="250.00")
    d9 = compute_compensation(u9)
    assert not d9.eligible
    assert d9.reason_code == "UNDELIVERED_PENDING"

    # Day 10 past estimate: full refund of R$250.00 (goodwill cap does NOT apply)
    u10 = make_order(is_delivered=False, status="shipped", days_past_estimate=10, order_value="250.00", payment_total="250.00")
    d10 = compute_compensation(u10)
    assert d10.eligible
    assert d10.kind == "full"
    assert d10.amount == Decimal("250.00")
    assert d10.policy_ref == "refund_policy#Undelivered"


def test_escalation_threshold_over_500():
    """Orders with order_value > R$500 require human escalation and are excluded from batch."""
    o_high = make_order(delay_days=10, freight_total="40.00", items_total="500.00", order_value="540.00", payment_total="540.00")
    d_high = compute_compensation(o_high)
    assert d_high.needs_escalation
    assert "exceeds escalation threshold" in d_high.escalation_reason

    # Batch builder excludes escalated orders
    batch = build_batch([d_high])
    assert len(batch.eligible_orders) == 0
    assert len(batch.excluded_orders) == 1
    assert batch.excluded_orders[0]["needs_escalation"] is True


def test_canceled_and_open_ticket_ineligibility():
    """Canceled orders or orders with open tickets are strictly ineligible."""
    o_canc = make_order(status="canceled", delay_days=12)
    d_canc = compute_compensation(o_canc)
    assert not d_canc.eligible
    assert d_canc.reason_code == "INELIGIBLE_STATUS"

    o_open = make_order(has_open_ticket=True, delay_days=12)
    d_open = compute_compensation(o_open)
    assert not d_open.eligible
    assert d_open.reason_code == "OPEN_TICKET_EXISTS"


def test_batch_limits_orders_cap_25():
    """Batch caps at 25 orders; 26th order is deferred to overflow."""
    decisions = []
    for i in range(26):
        decisions.append(
            RefundDecision(
                order_id=f"order_{i:03d}",
                eligible=True,
                tier="LATE_7",
                kind="goodwill",
                amount=Decimal("20.00"),
                reason_code="LATE_7",
                policy_ref="refund_policy#Tier LATE_7",
                needs_escalation=False,
                escalation_reason=None,
                ineligible_reason=None,
            )
        )

    batch = build_batch(decisions)
    assert len(batch.eligible_orders) == 25
    assert batch.overflow_count == 1
    assert batch.total_amount == Decimal("500.00")


def test_batch_limits_amount_cap_2000():
    """Batch total is strictly capped at R$2,000.00."""
    decisions = [
        RefundDecision(
            order_id=f"order_{i:02d}",
            eligible=True,
            tier="LATE_7",
            kind="goodwill",
            amount=Decimal("150.00"),
            reason_code="LATE_7",
            policy_ref="refund_policy#Tier LATE_7",
            needs_escalation=False,
            escalation_reason=None,
            ineligible_reason=None,
        )
        for i in range(16)  # 16 * 150 = 2400 > 2000
    ]

    batch = build_batch(decisions)
    # 13 * 150 = 1950 <= 2000; 14th would make 2100 > 2000
    assert len(batch.eligible_orders) == 13
    assert batch.total_amount == Decimal("1950.00")
    assert batch.overflow_count == 3
