"""Graph specialist subgraph runner.

Purpose:
    Executes graph traversal subtasks, validates Cypher patterns,
    and returns normalized Graph results for AgentState.
"""

from typing import Any, Dict, List
from ontoagent.agents.graph.nodes import run_graph_instruction
from ontoagent.graph.models import Subtask


async def run_graph_subgraph(
    subtasks: List[Subtask],
    use_fake: bool = False,
) -> Dict[str, Any]:
    """Execute graph specialist for designated graph subtasks.

    Args:
        subtasks: Decomposed subtasks from supervisor.
        use_fake: Whether to use fake LLM responses.

    Returns:
        Dictionary representation of GraphStepResult.
    """
    graph_subtasks = [st for st in subtasks if st.specialist == "graph"]
    if not graph_subtasks:
        return {
            "ok": True,
            "instruction": "",
            "cypher": None,
            "attempts": 0,
            "row_count": 0,
            "rows": [],
            "error_code": None,
            "error": None,
            "elapsed_ms": 0,
        }

    # Execute the primary graph subtask
    primary_task = graph_subtasks[0]
    result = await run_graph_instruction(
        instruction=primary_task.instruction,
        use_fake=use_fake,
    )
    return result.model_dump()
