"""Cryptographic HMAC approval token minting and verification.

Purpose:
    Protects MCP actions against direct invocation and token forgery (Threat T8).
    Binds tool name, approver identity, expiration timestamp, and arguments digest.
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional, Tuple
import uuid
from ontoagent.config import get_settings


def canonical_json(obj: Any) -> str:
    """Format object as deterministic canonical JSON string."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def base64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def base64url_decode(data_str: str) -> bytes:
    """Base64url decode with padding restoration."""
    padding = 4 - (len(data_str) % 4)
    if padding != 4:
        data_str += "=" * padding
    return base64.urlsafe_b64decode(data_str)


def compute_args_hash(args: Dict[str, Any]) -> str:
    """Calculate SHA256 digest of canonically serialized arguments."""
    return hashlib.sha256(canonical_json(args).encode("utf-8")).hexdigest()


def mint_approval_token(
    thread_id: str,
    tool: str,
    args: Dict[str, Any],
    approver: str,
    secret: Optional[str] = None,
    expires_in_s: int = 600,
) -> str:
    """Mint signed approval token bound to exact tool and arguments.

    Args:
        thread_id: Conversation thread identifier.
        tool: Target tool name (e.g. 'create_refund_ticket').
        args: Parameter payload dictionary.
        approver: Ops manager actor identifier.
        secret: Optional HMAC secret override.
        expires_in_s: Token validity duration (default 10 minutes).

    Returns:
        Token string format: base64url(payload) + '.' + base64url(signature)
    """
    if secret is None:
        secret = get_settings().approval_hmac_secret

    payload = {
        "jti": str(uuid.uuid4()),
        "thread_id": thread_id,
        "tool": tool,
        "args_sha256": compute_args_hash(args),
        "approver": approver,
        "exp": int(time.time()) + expires_in_s,
    }

    payload_json = canonical_json(payload).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), payload_json, hashlib.sha256).digest()

    return f"{base64url_encode(payload_json)}.{base64url_encode(sig)}"


def verify_approval_token(
    token: str,
    expected_tool: str,
    expected_args: Dict[str, Any],
    secret: Optional[str] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Verify approval token validity, tool binding, and argument hash.

    Args:
        token: Raw token string.
        expected_tool: Name of tool being invoked.
        expected_args: Actual argument dictionary passed to tool.
        secret: Optional HMAC secret override.

    Returns:
        Tuple: (valid: bool, reason: str, payload: dict | None)
    """
    if not token or "." not in token:
        return False, "Malformed token format", None

    parts = token.split(".")
    if len(parts) != 2:
        return False, "Invalid token segments", None

    if secret is None:
        secret = get_settings().approval_hmac_secret

    payload_b64, sig_b64 = parts[0], parts[1]

    try:
        payload_bytes = base64url_decode(payload_b64)
        sig_bytes = base64url_decode(sig_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as e:
        return False, f"Token decode failure: {str(e)}", None

    # Verify signature
    expected_sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(sig_bytes, expected_sig):
        return False, "Invalid HMAC signature", None

    # Check expiration
    now = int(time.time())
    if payload.get("exp", 0) < now:
        return False, "Token has expired", None

    # Check tool binding
    if payload.get("tool") != expected_tool:
        return False, f"Tool mismatch: expected {expected_tool}, got {payload.get('tool')}", None

    # Check argument hash binding
    computed_args_hash = compute_args_hash(expected_args)
    if payload.get("args_sha256") != computed_args_hash:
        return False, "Arguments do not match token digest", None

    return True, "Valid", payload
