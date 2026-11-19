"""Role-Based Access Control (RBAC) policy loader and validator.

Purpose:
    Loads policies/rbac.yaml and provides lookups for allowed tables,
    denied columns, and row-level access rules per persona (analyst vs ops_manager).
"""

from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel
import yaml


class RolePolicy(BaseModel):
    """Access policy definitions for a specific persona."""
    allowed_tables: List[str]
    denied_columns: List[str]
    row_level: str  # 'aggregate_only' or 'full'
    can_propose_actions: bool = False


_CACHED_POLICIES: Optional[Dict[str, RolePolicy]] = None


def load_rbac_policies(path: Optional[Path] = None) -> Dict[str, RolePolicy]:
    """Load role policies from rbac.yaml."""
    global _CACHED_POLICIES
    if _CACHED_POLICIES is not None and path is None:
        return _CACHED_POLICIES

    if path is None:
        path = Path("policies/rbac.yaml")
    if not path.is_absolute():
        path = Path.cwd() / path

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    roles_data = data.get("roles", {})
    parsed: Dict[str, RolePolicy] = {}
    for role_name, policy_dict in roles_data.items():
        parsed[role_name] = RolePolicy.model_validate(policy_dict)

    if path.name == "rbac.yaml":
        _CACHED_POLICIES = parsed
    return parsed


def get_role_policy(role: str) -> RolePolicy:
    """Retrieve policy for given role, defaulting to analyst if unknown."""
    policies = load_rbac_policies()
    if role not in policies:
        return policies.get(
            "analyst",
            RolePolicy(
                allowed_tables=["analytics.fct_orders"],
                denied_columns=[],
                row_level="aggregate_only",
                can_propose_actions=False,
            )
        )
    return policies[role]
