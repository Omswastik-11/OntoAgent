"""Unit tests for LangGraph StateGraph topology and routing invariants."""

import pytest
from langchain_core.messages import HumanMessage
from ontoagent.graph.builder import build_graph
from ontoagent.graph.models import RoutePlan, Subtask
from ontoagent.llm import FakeChatModel


@pytest.mark.asyncio
async def test_graph_builder_compiles():
    """Verify that StateGraph compiles successfully with checkpointer."""
    graph = build_graph()
    assert graph is not None


@pytest.mark.asyncio
async def test_fan_out_runs_synthesizer_exactly_once(monkeypatch):
    """Verify that compound SQL + RAG query executes both specialists and runs synthesizer once."""
    monkeypatch.setenv("ONTOAGENT_FAKE_LLM", "1")
    monkeypatch.setenv("ONTOAGENT_OFFLINE_FIXTURES", "1")

    # Mock FakeChatModel to return a compound RoutePlan
    compound_plan = RoutePlan(
        decision="answer",
        subtasks=[
            Subtask(specialist="sql", instruction="Calculate late delivery count"),
            Subtask(specialist="rag", instruction="Retrieve late delivery compensation policy"),
        ],
        wants_action=False,
        rationale="Compound operational query requiring SQL data and RAG policy",
    )

    fake_model = FakeChatModel()
    fake_model.structured_responses = [compound_plan]
    fake_model.responses = ["Synthesized final answer covering both SQL findings and RAG policy."]

    monkeypatch.setattr("ontoagent.graph.nodes.get_llm", lambda *a, **kw: fake_model)
    monkeypatch.setattr("ontoagent.agents.sql.nodes.get_llm", lambda *a, **kw: fake_model)

    graph = build_graph()
    res = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="Why were orders delayed in August 2018 and what does policy say?")],
            "user_role": "analyst",
            "actor_id": "test_actor",
        },
        config={"configurable": {"thread_id": "test_compound_topology"}}
    )

    # Assert both specialists populated results
    assert res.get("sql_results") is not None
    assert res.get("rag_result") is not None

    # Count how many times synthesizer produced an event
    synth_events = [e for e in res.get("events", []) if e.get("type") in ("synthesizer_done", "synthesizer_fail_closed")]
    assert len(synth_events) == 1, f"Synthesizer expected to run exactly once, ran {len(synth_events)} times"

    # Final text populated
    assert res.get("final_text") is not None


@pytest.mark.asyncio
async def test_empty_question_routes_directly_to_clarify(monkeypatch):
    """Verify empty input routes directly to clarify node without executing supervisor."""
    monkeypatch.setenv("ONTOAGENT_FAKE_LLM", "1")
    graph = build_graph()

    res = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="")],
            "user_role": "analyst",
            "actor_id": "test_actor",
        },
        config={"configurable": {"thread_id": "test_empty_topology"}}
    )

    assert "Please provide a valid question" in res.get("final_text", "")
    assert res.get("sql_results") is None
    assert res.get("rag_result") is None


@pytest.mark.asyncio
async def test_oversized_query_routes_directly_to_refuse(monkeypatch):
    """Verify query > 2000 chars routes directly to refuse without executing supervisor."""
    monkeypatch.setenv("ONTOAGENT_FAKE_LLM", "1")
    graph = build_graph()

    long_q = "What about order delays? " + ("A" * 2500)
    res = await graph.ainvoke(
        {
            "messages": [HumanMessage(content=long_q)],
            "user_role": "analyst",
            "actor_id": "test_actor",
        },
        config={"configurable": {"thread_id": "test_long_topology"}}
    )

    assert "too long" in res.get("final_text", "").lower()
    assert res.get("sql_results") is None
    assert res.get("rag_result") is None


@pytest.mark.asyncio
async def test_fan_out_routes_to_graph_specialist(monkeypatch):
    """Verify that graph specialist subtask routes to graph_specialist_node and populates graph_result."""
    monkeypatch.setenv("ONTOAGENT_FAKE_LLM", "1")
    monkeypatch.setenv("ONTOAGENT_OFFLINE_FIXTURES", "1")

    graph_plan = RoutePlan(
        decision="answer",
        subtasks=[
            Subtask(specialist="graph", instruction="Find sellers fulfilling orders with late shipments"),
        ],
        wants_action=False,
        rationale="Graph topology query",
    )

    fake_model = FakeChatModel()
    fake_model.structured_responses = [graph_plan]
    fake_model.responses = [
        "```cypher\nMATCH (s:Seller)-[:FULFILLS]->(o:Order) RETURN s.seller_id LIMIT 5;\n```",
        "Graph analysis identified 5 sellers with late shipments.",
    ]

    monkeypatch.setattr("ontoagent.graph.nodes.get_llm", lambda *a, **kw: fake_model)
    monkeypatch.setattr("ontoagent.agents.graph.nodes.get_llm", lambda *a, **kw: fake_model)

    graph = build_graph()
    res = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="Which sellers fulfilled orders with late shipments in Neo4j?")],
            "user_role": "analyst",
            "actor_id": "test_actor",
        },
        config={"configurable": {"thread_id": "test_graph_specialist_topology"}}
    )

    assert res.get("graph_result") is not None
    assert res.get("graph_result", {}).get("cypher") is not None
    assert "MATCH" in res["graph_result"]["cypher"]
    assert res.get("final_text") is not None

