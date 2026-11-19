"""RAG specialist wrapper.

Purpose:
    Executes policy document retrieval subtasks and packages RagResult for AgentState.
"""

from typing import Any, Dict, List
from ontoagent.agents.rag.nodes import run_rag_instruction
from ontoagent.graph.models import Subtask


async def run_rag_subgraph(
    subtasks: List[Subtask],
) -> Dict[str, Any]:
    """Run RAG specialist for designated policy subtask."""
    rag_subtasks = [st for st in subtasks if st.specialist == "rag"]
    if not rag_subtasks:
        return {"ok": True, "chunks": [], "citations": []}

    res = await run_rag_instruction(rag_subtasks[0].instruction)
    return res.model_dump()
