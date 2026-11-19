"""Structured Pydantic models for orchestration routing and specialist steps.

Purpose:
    Typed schemas for LLM structured outputs and specialist results.
    Ensures state boundaries only transfer validated, serializable payloads.
"""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class Subtask(BaseModel):
    """An individual query or retrieval subtask delegated to a specialist."""
    specialist: Literal["sql", "graph", "rag"]
    instruction: str = Field(max_length=500, description="Self-contained specialist prompt")


class RoutePlan(BaseModel):
    """Supervisor routing decision and decomposition plan."""
    decision: Literal["answer", "clarify", "refuse"] = "answer"
    subtasks: List[Subtask] = Field(default_factory=list, max_length=5)
    wants_action: bool = False
    action_type: Literal["refund", "notify_seller", "none"] = "none"
    clarification_question: Optional[str] = None
    refusal_reason: Optional[str] = None
    rationale: str = "Decomposed plan based on user intent"


class SqlStepResult(BaseModel):
    """Result payload produced by an SQL specialist subgraph step."""
    ok: bool
    instruction: str
    sql: Optional[str] = None
    attempts: int = 1
    columns: List[str] = Field(default_factory=list)
    row_count: int = 0
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    digest: Dict[str, Any] = Field(default_factory=dict)
    candidate_ids: List[str] = Field(default_factory=list)
    error_code: Optional[str] = None
    error: Optional[str] = None
    elapsed_ms: int = 0


class GraphStepResult(BaseModel):
    """Result payload produced by a Graph specialist subgraph step."""
    ok: bool
    instruction: str
    cypher: Optional[str] = None
    attempts: int = 1
    row_count: int = 0
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    error_code: Optional[str] = None
    error: Optional[str] = None
    elapsed_ms: int = 0


class RagChunk(BaseModel):
    """Retrieved policy documentation chunk with citation metadata."""
    chunk_id: int
    doc_id: str
    doc_title: str
    section: str
    citation_anchor: str
    content: str
    score: float = 0.0
    trust_level: str = "internal"
    quarantined: bool = False


class RagResult(BaseModel):
    """Result payload produced by the RAG specialist subgraph."""
    ok: bool
    instruction: str
    chunks: List[RagChunk] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    quarantined_count: int = 0
    error: Optional[str] = None
    elapsed_ms: int = 0
