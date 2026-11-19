"""Unit and endpoint integration tests for OntoAgent FastAPI service.

Purpose:
    Validates health endpoint, authentication middleware, role filtering on ontology,
    turn execution, role gating on approval endpoints, and state retrieval.
"""

import os
import pytest
from fastapi.testclient import TestClient

os.environ["ONTOAGENT_FAKE_LLM"] = "1"
os.environ["ONTOAGENT_ENVIRONMENT"] = "test"

from ontoagent.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_endpoint(client):
    """Test health check returns components and status."""
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "components" in data
    assert "postgres" in data["components"]
    assert "llm" in data["components"]
    assert "mcp" in data["components"]
    assert data["version"] == "0.1.0"


def test_ontology_endpoint_requires_auth(client):
    """Test /v1/ontology rejects unauthenticated requests."""
    resp = client.get("/v1/ontology")
    assert resp.status_code == 401
    assert "X-API-Key" in resp.json().get("detail", "")


def test_ontology_endpoint_analyst_role(client):
    """Test /v1/ontology returns filtered view for analyst role."""
    resp = client.get(
        "/v1/ontology",
        headers={"X-API-Key": "sk-analyst-test"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "analyst"
    assert "entities" in data
    assert "metrics" in data


def test_ontology_endpoint_ops_role(client):
    """Test /v1/ontology returns full view for ops_manager role."""
    resp = client.get(
        "/v1/ontology",
        headers={"X-API-Key": "sk-ops-test"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "ops_manager"
    assert "entities" in data


def test_chat_turn_unauthenticated(client):
    """Test chat endpoint rejects unauthenticated caller."""
    resp = client.post("/v1/chat", json={"message": "How many orders were delivered?"})
    assert resp.status_code == 401


def test_chat_turn_analyst(client):
    """Test chat turn execution for authenticated analyst."""
    resp = client.post(
        "/v1/chat",
        headers={"X-API-Key": "sk-analyst-test"},
        json={"message": "How many orders have been delivered in total?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "analyst"
    assert "thread_id" in data
    assert "trace_id" in data
    assert "answer" in data
    assert isinstance(data["citations"], list)
    assert "queries" in data


def test_approval_endpoint_analyst_forbidden(client):
    """Test that analyst is rejected from approval endpoint with 403 Forbidden."""
    resp = client.post(
        "/v1/threads/sess_test_123/approval",
        headers={"X-API-Key": "sk-analyst-test"},
        json={"approved": True, "reason": "Analyst attempting approval"},
    )
    assert resp.status_code == 403
    assert "Forbidden" in resp.json().get("detail", "")


def test_approval_endpoint_non_interrupted_thread(client):
    """Test that ops_manager approval on non-interrupted thread returns 400 Bad Request."""
    resp = client.post(
        "/v1/threads/non_existent_thread_xyz/approval",
        headers={"X-API-Key": "sk-ops-test"},
        json={"approved": True, "reason": "Operator approve"},
    )
    assert resp.status_code == 400
    assert "not in an interrupted approval state" in resp.json().get("detail", "")


def test_get_thread_state_unknown(client):
    """Test thread retrieval for non-existent thread returns 404."""
    resp = client.get(
        "/v1/threads/completely_unknown_thread_12345",
        headers={"X-API-Key": "sk-analyst-test"},
    )
    assert resp.status_code == 404


def test_interrupted_turn_and_approval_narrowing(client, monkeypatch):
    """Test full API flow: turn requests action -> interrupted -> approval with narrowing -> executed."""
    from decimal import Decimal
    from ontoagent.actions.policy_engine import OrderFacts
    from ontoagent.graph.models import RoutePlan, Subtask
    from ontoagent.llm import FakeChatModel

    facts = [
        OrderFacts(
            order_id="test_ord_api_01",
            order_status="delivered",
            is_delivered=True,
            delay_days=10,
            days_past_estimate_as_of=0,
            items_total=Decimal("80.00"),
            freight_total=Decimal("35.00"),
            order_value=Decimal("115.00"),
            payment_total=Decimal("115.00"),
            has_open_ticket=False,
        ),
        OrderFacts(
            order_id="test_ord_api_02",
            order_status="delivered",
            is_delivered=True,
            delay_days=16,
            days_past_estimate_as_of=0,
            items_total=Decimal("100.00"),
            freight_total=Decimal("25.00"),
            order_value=Decimal("125.00"),
            payment_total=Decimal("125.00"),
            has_open_ticket=False,
        ),
    ]

    action_plan = RoutePlan(
        decision="answer",
        subtasks=[Subtask(specialist="sql", instruction="Find delayed orders to compensate")],
        wants_action=True,
        action_type="refund",
        rationale="Operational manager requested compensation for delayed orders.",
    )

    fake_model = FakeChatModel()
    fake_model.structured_responses = [action_plan]
    fake_model.responses = ["Identified 2 orders meeting delay compensation criteria."]

    monkeypatch.setattr("ontoagent.graph.nodes.get_llm", lambda *a, **kw: fake_model)
    monkeypatch.setattr("ontoagent.agents.sql.nodes.get_llm", lambda *a, **kw: fake_model)
    monkeypatch.setattr("ontoagent.actions.planner.fetch_order_facts", lambda *a, **kw: facts)

    # 1. Execute turn as ops_manager requesting refund
    turn_resp = client.post(
        "/v1/chat",
        headers={"X-API-Key": "sk-ops-test"},
        json={"message": "Please issue refund compensation for late orders."},
    )
    assert turn_resp.status_code == 200
    turn_data = turn_resp.json()
    assert turn_data["interrupted"] is True
    assert turn_data["proposed_action"] is not None
    assert len(turn_data["proposed_action"]["items"]) == 2
    thread_id = turn_data["thread_id"]

    # 2. Call approval endpoint narrowing to test_ord_api_01 only
    app_resp = client.post(
        f"/v1/threads/{thread_id}/approval",
        headers={"X-API-Key": "sk-ops-test"},
        json={
            "approved": True,
            "narrow_order_ids": ["test_ord_api_01"],
            "reason": "Approved order 1 only; order 2 deferred",
        },
    )
    assert app_resp.status_code == 200
    app_data = app_resp.json()
    assert app_data["interrupted"] is False
    assert app_data["approved"] is True
    assert app_data["action_result"] is not None
    # Verify narrowed orders executed
    results = app_data["action_result"].get("results") or []
    executed_ids = [r["order_id"] for r in results]
    assert executed_ids == ["test_ord_api_01"]
    assert "test_ord_api_02" not in executed_ids

