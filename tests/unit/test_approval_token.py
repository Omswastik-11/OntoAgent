"""Unit tests for cryptographic approval token minting and verification (Threat T8)."""

import time
from ontoagent.guards.approval_token import mint_approval_token, verify_approval_token


def test_valid_token_verifies():
    args = {"order_id": "order_123", "amount": "45.00"}
    token = mint_approval_token(
        thread_id="t1",
        tool="create_refund_ticket",
        args=args,
        approver="omar",
        secret="test_secret_key_12345"
    )
    valid, reason, payload = verify_approval_token(
        token=token,
        expected_tool="create_refund_ticket",
        expected_args=args,
        secret="test_secret_key_12345"
    )
    assert valid, f"Token verification failed: {reason}"
    assert payload["approver"] == "omar"


def test_tampered_signature_fails():
    args = {"order_id": "order_123", "amount": "45.00"}
    token = mint_approval_token(
        thread_id="t1",
        tool="create_refund_ticket",
        args=args,
        approver="omar",
        secret="test_secret_key_12345"
    )
    # Corrupt last character of signature
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    valid, reason, _ = verify_approval_token(
        token=tampered,
        expected_tool="create_refund_ticket",
        expected_args=args,
        secret="test_secret_key_12345"
    )
    assert not valid
    assert "Invalid HMAC signature" in reason or "Token decode failure" in reason


def test_argument_mismatch_fails():
    args = {"order_id": "order_123", "amount": "45.00"}
    token = mint_approval_token(
        thread_id="t1",
        tool="create_refund_ticket",
        args=args,
        approver="omar",
        secret="test_secret_key_12345"
    )
    # Attempt execution with higher amount
    hacked_args = {"order_id": "order_123", "amount": "450.00"}
    valid, reason, _ = verify_approval_token(
        token=token,
        expected_tool="create_refund_ticket",
        expected_args=hacked_args,
        secret="test_secret_key_12345"
    )
    assert not valid
    assert "Arguments do not match token digest" in reason


def test_expired_token_fails():
    args = {"order_id": "order_123", "amount": "45.00"}
    token = mint_approval_token(
        thread_id="t1",
        tool="create_refund_ticket",
        args=args,
        approver="omar",
        secret="test_secret_key_12345",
        expires_in_s=-10  # already expired
    )
    valid, reason, _ = verify_approval_token(
        token=token,
        expected_tool="create_refund_ticket",
        expected_args=args,
        secret="test_secret_key_12345"
    )
    assert not valid
    assert "expired" in reason.lower()
