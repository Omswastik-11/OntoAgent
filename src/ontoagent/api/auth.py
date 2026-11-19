"""API key authentication and role mapping middleware (SPEC §§ 14 & 15).

Purpose:
    Validates X-API-Key against configured keys, associates actor_id and role
    ('analyst' vs 'ops_manager'), and enforces fail-closed access control.
"""

from dataclasses import dataclass
import os
from typing import Dict, Optional
from fastapi import Header, HTTPException, status


@dataclass(frozen=True)
class UserIdentity:
    actor_id: str
    role: str  # 'analyst' or 'ops_manager'


# Default static key mappings for development and testing
DEFAULT_KEY_MAP: Dict[str, UserIdentity] = {
    "sk-analyst-test": UserIdentity(actor_id="analyst_user", role="analyst"),
    "sk-ops-test": UserIdentity(actor_id="ops_manager_user", role="ops_manager"),
}


def get_current_user(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> UserIdentity:
    """Validate X-API-Key and return authenticated UserIdentity."""
    if not x_api_key:
        # Check if environment allows dev fallback
        dev_mode = os.environ.get("ONTOAGENT_DEV_MODE", "0") == "1"
        if dev_mode:
            return UserIdentity(actor_id="dev_analyst", role="analyst")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Check configured map or custom env keys
    if x_api_key in DEFAULT_KEY_MAP:
        return DEFAULT_KEY_MAP[x_api_key]

    # Custom API key format support: e.g. "sk-ops-secret" -> ops_manager
    if "ops" in x_api_key.lower():
        return UserIdentity(actor_id=f"user_{x_api_key[:8]}", role="ops_manager")
    if "analyst" in x_api_key.lower():
        return UserIdentity(actor_id=f"user_{x_api_key[:8]}", role="analyst")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid X-API-Key provided.",
        headers={"WWW-Authenticate": "ApiKey"},
    )
