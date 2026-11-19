"""LangGraph AgentState schema with turn lifecycle reducers.

Purpose:
    Defines persisted and per-turn state attributes.
    Uses accumulate reducer with sentinel RESET to avoid state leakage across turns (Threat T10).
"""

from typing import Annotated, Any, Dict, List, Literal, Optional
from typing_extensions import TypedDict
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

RESET = "__RESET__"


def accumulate(old: Optional[List[Any]], new: Optional[List[Any]]) -> List[Any]:
    """Reducer: appends new items unless new starts with RESET, which overwrites."""
    old_list = old or []
    if new and len(new) > 0 and new[0] == RESET:
        return list(new[1:])
    if not new:
        return list(old_list)
    return list(old_list) + list(new)


class AgentState(TypedDict, total=False):
    # ---- Persisted across turns on the same thread ----
    messages: Annotated[List[AnyMessage], add_messages]
    last_candidate_order_ids: List[str]

    # ---- Identity (set by API/auth, never by LLM) ----
    user_role: Literal["analyst", "ops_manager"]
    actor_id: str

    # ---- Per-turn state (reset at turn start by init_turn) ----
    question: str
    time_context: Dict[str, Any]
    risk_flags: Annotated[List[str], accumulate]
    plan: Optional[Dict[str, Any]]
    sql_results: Optional[List[Dict[str, Any]]]
    graph_result: Optional[Dict[str, Any]]
    rag_result: Optional[Dict[str, Any]]
    draft_answer: Optional[str]
    answer: Optional[str]
    citations: List[str]
    proposed_action: Optional[Dict[str, Any]]
    approval: Optional[Dict[str, Any]]
    action_outcome: Optional[Dict[str, Any]]
    action_result: Optional[Dict[str, Any]]
    final_text: Optional[str]
    errors: Annotated[List[str], accumulate]
    events: Annotated[List[Dict[str, Any]], accumulate]
