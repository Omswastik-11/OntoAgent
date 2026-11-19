"""LangGraph StateGraph builder for OntoAgent orchestration.

Purpose:
    Assembles specialist nodes, parallel fan-out conditional edges,
    action planning gates, human-in-the-loop interrupts, and checkpointing
    into a compiled runnable graph.
"""

from typing import Any, Optional
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from ontoagent.graph.nodes import (
    action_planner_node,
    clarify_node,
    finalize_node,
    graph_specialist_node,
    human_approval_node,
    init_turn,
    input_guard,
    mcp_executor_node,
    rag_specialist_node,
    refuse_node,
    sql_specialist_node,
    supervisor,
    synthesizer,
)
from ontoagent.graph.routing import (
    after_approval,
    after_input_guard,
    after_planner,
    after_synthesizer,
    fan_out,
)
from ontoagent.graph.state import AgentState


def build_graph(checkpointer: Optional[Any] = None) -> Any:
    """Build and compile the OntoAgent orchestration graph.

    Args:
        checkpointer: Optional LangGraph checkpointer instance (defaults to MemorySaver).

    Returns:
        Compiled StateGraph runnable.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    builder = StateGraph(AgentState)

    # Add orchestration and specialist nodes
    builder.add_node("init_turn", init_turn)
    builder.add_node("input_guard", input_guard)
    builder.add_node("supervisor", supervisor)
    builder.add_node("sql_specialist", sql_specialist_node)
    builder.add_node("graph_specialist", graph_specialist_node)
    builder.add_node("rag_specialist", rag_specialist_node)
    builder.add_node("synthesizer", synthesizer)
    builder.add_node("action_planner", action_planner_node)
    builder.add_node("human_approval", human_approval_node)
    builder.add_node("mcp_executor", mcp_executor_node)
    builder.add_node("clarify", clarify_node)
    builder.add_node("refuse", refuse_node)
    builder.add_node("finalize", finalize_node)

    # Primary entry flow
    builder.add_edge(START, "init_turn")
    builder.add_edge("init_turn", "input_guard")

    # Guard conditional routing
    builder.add_conditional_edges(
        "input_guard",
        after_input_guard,
        {"supervisor": "supervisor", "refuse": "refuse", "clarify": "clarify"},
    )

    # Supervisor parallel fan-out
    builder.add_conditional_edges(
        "supervisor",
        fan_out,
        ["sql_specialist", "rag_specialist", "graph_specialist", "clarify", "refuse"],
    )

    # Join specialists into single synthesizer execution
    builder.add_edge("sql_specialist", "synthesizer")
    builder.add_edge("graph_specialist", "synthesizer")
    builder.add_edge("rag_specialist", "synthesizer")

    # Post-synthesizer action routing gate (ops_manager + wants_action only)
    builder.add_conditional_edges(
        "synthesizer",
        after_synthesizer,
        {"action_planner": "action_planner", "finalize": "finalize"},
    )

    # Action planning to human approval interrupt
    builder.add_conditional_edges(
        "action_planner",
        after_planner,
        {"human_approval": "human_approval", "finalize": "finalize"},
    )

    # Human approval to MCP tool execution
    builder.add_conditional_edges(
        "human_approval",
        after_approval,
        {"mcp_executor": "mcp_executor", "finalize": "finalize"},
    )

    # Finalization edges
    builder.add_edge("mcp_executor", "finalize")
    builder.add_edge("clarify", "finalize")
    builder.add_edge("refuse", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=checkpointer)
