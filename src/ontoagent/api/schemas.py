"""Pydantic schemas for the OntoAgent REST API.

Purpose:
    Defines request, response, approval, and audit models for API communication.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class HealthComponent(BaseModel):
    status: str
    latency_ms: Optional[float] = None
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    status: str = Field(..., description="'ok' or 'degraded'")
    components: Dict[str, HealthComponent]
    as_of_date: str
    version: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="User question or instruction")
    thread_id: Optional[str] = Field(None, description="Session thread ID for stateful conversation")
    as_of: Optional[str] = Field(None, description="Optional override for historical as-of date (YYYY-MM-DD)")


class ProposedActionSummary(BaseModel):
    batch_id: str
    tool: str
    items_count: int
    total_amount: str
    expires_in_s: int = 900
    token: str
    items: List[Dict[str, Any]] = []


class ChatResponse(BaseModel):
    thread_id: str
    trace_id: str
    role: str
    actor_id: str
    answer: str
    citations: List[str] = []
    queries: Dict[str, Any] = {}
    proposed_action: Optional[Dict[str, Any]] = None
    interrupted: bool = False
    approved: Optional[bool] = None
    action_result: Optional[Dict[str, Any]] = None
    risk_flags: List[str] = []
    events: List[Dict[str, Any]] = []


class ApprovalRequest(BaseModel):
    approved: bool = Field(..., description="True to execute the action; False to reject")
    narrow_order_ids: Optional[List[str]] = Field(None, description="Optional subset of candidate order IDs to approve")
    reason: Optional[str] = Field(None, description="Human auditor justification or rejection reason")


class ThreadResponse(BaseModel):
    thread_id: str
    state: Dict[str, Any]
    history: List[Dict[str, Any]]
