"""Conditional routing edges for the OntoAgent LangGraph state graph.

Purpose:
    Directs turn execution flow based on input guards, supervisor decomposition,
    specialist fan-out, action planning gates, and human approval transitions.
"""

from typing import List, Literal
from ontoagent.graph.state import AgentState

HARD_ACTION_RISK_FLAGS = {
    "GUARD_ERROR",
    "ACTION_LANGUAGE_IN_UNTRUSTED",
    "USER_INJECTION_HARD",
}


def after_input_guard(state: AgentState) -> Literal["supervisor", "refuse", "clarify"]:
    """Route after input guard: refuse if hard errors exist, clarify if empty, else proceed to supervisor."""
    question = state.get("question", "")
    risk_flags = state.get("risk_flags", [])
    errors = state.get("errors", [])

    if not question or not question.strip() or "EMPTY_QUESTION" in risk_flags:
        return "clarify"
    if "QUERY_TOO_LONG" in risk_flags or any("exceeds maximum" in str(e).lower() for e in errors):
        return "refuse"
    return "supervisor"


def fan_out(state: AgentState) -> List[str]:
    """Parallel fan-out: return list of specialist node names based on plan subtasks."""
    plan = state.get("plan") or {}
    decision = plan.get("decision", "answer")

    if decision == "clarify":
        return ["clarify"]
    if decision == "refuse":
        return ["refuse"]

    subtasks = plan.get("subtasks", [])
    if not subtasks:
        return ["sql_specialist"]

    nodes_to_run = set()
    for st in subtasks:
        spec = st.get("specialist") if isinstance(st, dict) else getattr(st, "specialist", "")
        if spec == "sql":
            nodes_to_run.add("sql_specialist")
        elif spec == "rag":
            nodes_to_run.add("rag_specialist")
        elif spec == "graph":
            nodes_to_run.add("graph_specialist")

    if not nodes_to_run:
        nodes_to_run.add("sql_specialist")

    return list(nodes_to_run)


def after_synthesizer(state: AgentState) -> Literal["action_planner", "finalize"]:
    """Route after synthesizer: evaluate whether operational action planning should run.

    Invariant (SPEC §10.2):
        action_planner only runs if:
            1. plan.wants_action is True
            2. user_role == "ops_manager" (Analyst role NEVER reaches planner)
            3. No hard risk flags present
    """
    plan = state.get("plan") or {}
    wants_action = plan.get("wants_action", False)
    role = state.get("user_role", "analyst")
    risk_flags = state.get("risk_flags", [])

    has_hard_risk = any(f in HARD_ACTION_RISK_FLAGS for f in risk_flags)

    if wants_action and role == "ops_manager" and not has_hard_risk:
        return "action_planner"
    return "finalize"


def after_planner(state: AgentState) -> Literal["human_approval", "finalize"]:
    """Route after action_planner: trigger human approval if any orders qualified."""
    proposed = state.get("proposed_action") or {}
    items = proposed.get("items", [])
    if items and len(items) > 0:
        return "human_approval"
    return "finalize"


def after_approval(state: AgentState) -> Literal["mcp_executor", "finalize"]:
    """Route after human_approval: proceed to MCP executor if approved, else finalize."""
    approval = state.get("approval") or {}
    decision = approval.get("decision")
    if decision == "approve":
        return "mcp_executor"
    return "finalize"
