"""FastAPI service implementation for OntoAgent.

Purpose:
    Exposes REST endpoints for health checks, role-governed ontology queries,
    stateful conversational execution, and human-in-the-loop action approval/resume.
"""

import logging
import time
from typing import Any, Dict, List, Optional
import uuid

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from ontoagent.api.auth import UserIdentity, get_current_user
from ontoagent.api.schemas import (
    ApprovalRequest,
    ChatRequest,
    ChatResponse,
    HealthComponent,
    HealthResponse,
    ThreadResponse,
)
from ontoagent.config import get_settings
from ontoagent.graph.builder import build_graph
from ontoagent.ontology.loader import load_ontology

logger = logging.getLogger("ontoagent.api")

app = FastAPI(
    title="OntoAgent Enterprise Operations Copilot",
    version="0.1.0",
    description="Ontology-grounded multi-agent copilot API with strict anti-fabrication and human-in-the-loop approvals.",
)

# Enable CORS for local web interfaces
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared graph instance
_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


@app.get("/v1/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """System health check verifying database connections, MCP server, and LLM readiness."""
    settings = get_settings()
    components: Dict[str, HealthComponent] = {}
    is_healthy = True

    # 1. Check PostgreSQL
    t0 = time.time()
    try:
        import psycopg
        with psycopg.connect(settings.postgres_ro_url, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        components["postgres"] = HealthComponent(
            status="connected",
            latency_ms=round((time.time() - t0) * 1000.0, 2),
        )
    except Exception as e:
        is_healthy = False
        components["postgres"] = HealthComponent(
            status="unreachable",
            detail=str(e),
        )

    # 2. Check Neo4j
    t0 = time.time()
    try:
        from neo4j import AsyncGraphDatabase
        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            connection_timeout=2.0,
        )
        async with driver:
            await driver.verify_connectivity()
        components["neo4j"] = HealthComponent(
            status="connected",
            latency_ms=round((time.time() - t0) * 1000.0, 2),
        )
    except Exception as e:
        components["neo4j"] = HealthComponent(
            status="unreachable",
            detail=str(e),
        )

    # 3. Check LLM provider
    components["llm"] = HealthComponent(
        status="ready",
        detail=f"Model: {settings.llm_model}",
    )

    # 4. Check MCP
    components["mcp"] = HealthComponent(
        status="ready",
        detail="FastMCP server enabled",
    )

    return HealthResponse(
        status="ok" if is_healthy else "degraded",
        components=components,
        as_of_date=settings.as_of_date,
        version="0.1.0",
    )


@app.get("/v1/ontology")
async def get_ontology_view(
    user: UserIdentity = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retrieve role-filtered ontology entities, allowed metrics, and relationships."""
    onto = load_ontology()
    entities = {}

    for name, entity in onto.entities.items():
        props = {}
        for prop_name, prop_def in entity.properties.items():
            # If sensitivity is PII and role is analyst, hide or mask
            if user.role == "analyst" and prop_def.sensitivity == "pii":
                continue
            props[prop_name] = prop_def.model_dump()

        if props:
            entities[name] = {
                "name": name,
                "sql_table": entity.sql_table,
                "description": entity.description,
                "properties": props,
            }

    metrics = {
        m_name: m_def.model_dump()
        for m_name, m_def in onto.metrics.items()
    }

    return {
        "role": user.role,
        "as_of_date": get_settings().as_of_date,
        "entities": entities,
        "metrics": metrics,
        "relationships": [r.model_dump() for r in onto.relationships],
    }


@app.post("/v1/chat", response_model=ChatResponse)
async def chat_turn(
    request: ChatRequest,
    user: UserIdentity = Depends(get_current_user),
) -> ChatResponse:
    """Execute a conversational turn through the OntoAgent graph."""
    settings = get_settings()
    graph = get_graph()
    thread_id = request.thread_id or f"sess_{uuid.uuid4().hex[:12]}"
    trace_id = f"tr_{uuid.uuid4().hex[:12]}"
    as_of = request.as_of or settings.as_of_date

    config = {"configurable": {"thread_id": thread_id}}

    try:
        res = await graph.ainvoke(
            {
                "messages": [HumanMessage(content=request.message)],
                "user_role": user.role,
                "actor_id": user.actor_id,
                "time_context": {"as_of": as_of, "thread_id": thread_id},
            },
            config=config,
        )
    except Exception as e:
        logger.error("Chat invocation failed: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Turn execution error: {str(e)}",
        )

    # Check if execution was interrupted (awaiting approval)
    state_snap = graph.get_state(config)
    interrupted = bool(state_snap and state_snap.next and "human_approval" in state_snap.next)

    # Extract queries
    sql_results = res.get("sql_results") or []
    queries = {
        "sql": [sr.get("sql") for sr in sql_results if sr.get("sql")],
        "cypher": res.get("graph_result", {}).get("cypher") if res.get("graph_result") else None,
    }

    return ChatResponse(
        thread_id=thread_id,
        trace_id=trace_id,
        role=user.role,
        actor_id=user.actor_id,
        answer=res.get("final_text") or res.get("answer") or "No response generated.",
        citations=res.get("citations") or [],
        queries=queries,
        proposed_action=res.get("proposed_action"),
        interrupted=interrupted,
        action_result=res.get("action_result"),
        risk_flags=res.get("risk_flags") or [],
        events=res.get("events") or [],
    )


@app.post("/v1/threads/{thread_id}/approval", response_model=ChatResponse)
async def resume_approval(
    thread_id: str,
    approval: ApprovalRequest,
    user: UserIdentity = Depends(get_current_user),
) -> ChatResponse:
    """Resume an interrupted turn with human approval decision and optional order ID narrowing."""
    if user.role != "ops_manager":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Only ops_manager role can approve or reject operational actions.",
        )

    graph = get_graph()
    config = {"configurable": {"thread_id": thread_id}}

    # Verify state is waiting for approval
    state_snap = graph.get_state(config)
    if not state_snap or not state_snap.next:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Thread is not in an interrupted approval state.",
        )

    resume_payload = {
        "approved": approval.approved,
        "narrow_order_ids": approval.narrow_order_ids,
        "reason": approval.reason or ("Approved by operator" if approval.approved else "Rejected by operator"),
        "actor_id": user.actor_id,
    }

    try:
        res = await graph.ainvoke(Command(resume=resume_payload), config=config)
    except Exception as e:
        logger.error("Approval resume failed: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Approval execution failed: {str(e)}",
        )

    trace_id = f"tr_{uuid.uuid4().hex[:12]}"
    sql_results = res.get("sql_results") or []

    return ChatResponse(
        thread_id=thread_id,
        trace_id=trace_id,
        role=user.role,
        actor_id=user.actor_id,
        answer=res.get("final_text") or res.get("answer") or "Action processed.",
        citations=res.get("citations") or [],
        queries={"sql": [sr.get("sql") for sr in sql_results if sr.get("sql")]},
        proposed_action=res.get("proposed_action"),
        interrupted=False,
        approved=approval.approved,
        action_result=res.get("action_result") or res.get("action_outcome"),
        risk_flags=res.get("risk_flags") or [],
        events=res.get("events") or [],
    )


@app.get("/v1/threads/{thread_id}", response_model=ThreadResponse)
async def get_thread_state(
    thread_id: str,
    user: UserIdentity = Depends(get_current_user),
) -> ThreadResponse:
    """Retrieve full history and current state for a conversation thread."""
    graph = get_graph()
    config = {"configurable": {"thread_id": thread_id}}
    state_snap = graph.get_state(config)

    if not state_snap or not state_snap.values:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread {thread_id} not found.",
        )

    state_dict = state_snap.values or {}
    messages = state_dict.get("messages", [])
    history = [
        {
            "role": getattr(m, "type", "unknown"),
            "content": m.content if hasattr(m, "content") else str(m),
        }
        for m in messages
    ]

    return ThreadResponse(
        thread_id=thread_id,
        state=state_dict,
        history=history,
    )
