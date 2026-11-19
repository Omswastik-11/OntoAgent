"""SQL specialist wrapper.

Purpose:
    Executes up to 3 subtasks sequentially and packages SqlStepResult list for AgentState.
"""

from typing import Any, Dict, List
from ontoagent.agents.sql.nodes import run_sql_instruction
from ontoagent.graph.models import Subtask


async def run_sql_subgraph(
    subtasks: List[Subtask],
    role: str = "analyst",
    as_of: str = "2018-09-01",
    use_fake: bool = False,
) -> List[Dict[str, Any]]:
    """Run SQL specialist for a list of subtasks (up to 3)."""
    results: List[Dict[str, Any]] = []
    sql_subtasks = [st for st in subtasks if st.specialist == "sql"][:3]

    for st in sql_subtasks:
        res = await run_sql_instruction(
            instruction=st.instruction,
            role=role,
            as_of=as_of,
            use_fake=use_fake,
        )
        results.append(res.model_dump())

    return results
