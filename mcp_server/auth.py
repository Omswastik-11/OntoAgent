"""Cryptographic HMAC approval token verification for MCP Server.

Purpose:
    Maintains independent verification logic within the isolated MCP Server trust domain.
    Ensures zero coupling or import dependency from the main application package.
    Enforces tool binding, canonical argument digest, and token expiration.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional, Tuple


def canonical_json(obj: Any) -> str:
    """Format object as deterministic canonical JSON string."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def base64url_decode(data_str: str) -> bytes:
    """Base64url decode with padding restoration."""
    padding = 4 - (len(data_str) % 4)
    if padding != 4:
        data_str += "=" * padding
    return base64.urlsafe_b64decode(data_str)


def compute_args_hash(args: Dict[str, Any]) -> str:
    """Calculate SHA256 digest of canonically serialized arguments."""
    return hashlib.sha256(canonical_json(args).encode("utf-8")).hexdigest()


def verify_approval_token(
    token: str,
    expected_tool: str,
    expected_args: Dict[str, Any],
    secret: Optional[str] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Verify approval token validity, tool binding, and argument hash.

    Args:
        token: Raw token string format: base64url(payload) + '.' + base64url(signature).
        expected_tool: Target tool name.
        expected_args: Actual arguments passed to tool (excluding approval_token itself).
        secret: Optional secret override (defaults to APPROVAL_HMAC_SECRET env).

    Returns:
        Tuple: (valid: bool, reason: str, payload: dict | None)
    """
    if not token or "." not in token:
        return False, "Malformed token format", None

    parts = token.split(".")
    if len(parts) != 2:
        return False, "Invalid token segments", None

    if secret is None:
        secret = os.getenv("APPROVAL_HMAC_SECRET", "c8e7b1a2d3f4e5a6b7c8d9e0f1a2b3c4")

    payload_b64, sig_b64 = parts[0], parts[1]

    try:
        payload_bytes = base64url_decode(payload_b64)
        sig_bytes = base64url_decode(sig_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as e:
        return False, f"Token decode failure: {str(e)}", None

    # 1. Constant-time signature verification
    expected_sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(sig_bytes, expected_sig):
        return False, "Invalid HMAC signature", None

    # 2. Check expiration
    now = int(time.time())
    if payload.get("exp", 0) < now:
        return False, "Token has expired", None

    # 3. Check tool binding
    if payload.get("tool") != expected_tool:
        return False, f"Tool mismatch: expected {expected_tool}, got {payload.get('tool')}", None

    # 4. Check argument hash binding
    computed_args_hash = compute_args_hash(expected_args)
    if payload.get("args_sha256") != computed_args_hash:
        return False, "Arguments do not match token digest", None

    return True, "Valid", payload
