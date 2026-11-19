"""Consistency tests between policy YAML definitions and human-readable documentation."""

from pathlib import Path
import yaml


def test_refund_policy_yaml_doc_consistency():
    yaml_path = Path("policies/refund_policy.yaml")
    doc_path = Path("policies/docs/refund_policy.md")

    with open(yaml_path, "r", encoding="utf-8") as f:
        policy_data = yaml.safe_load(f)

    doc_text = doc_path.read_text(encoding="utf-8")

    # Assert key numerical figures are in both
    goodwill_cap = str(int(policy_data["caps"]["goodwill_cap"]))
    assert goodwill_cap in doc_text, f"Goodwill cap {goodwill_cap} missing from {doc_path}"

    max_orders = str(policy_data["caps"]["batch_max_orders"])
    assert max_orders in doc_text, f"Batch max orders {max_orders} missing from {doc_path}"

    batch_amount = int(policy_data["caps"]["batch_max_amount"])
    assert (str(batch_amount) in doc_text or f"{batch_amount:,}" in doc_text), f"Batch amount {batch_amount} missing from {doc_path}"

    undelivered_days = str(policy_data["undelivered"]["min_days_past_estimate"])
    assert undelivered_days in doc_text, f"Undelivered threshold {undelivered_days} missing from {doc_path}"
