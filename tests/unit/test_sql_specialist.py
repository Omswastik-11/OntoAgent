"""Unit tests for the SQL specialist subgraph and Bug B1/B6 invariants."""

import pytest
from ontoagent.agents.sql.nodes import run_sql_instruction
from ontoagent.errors import DatabaseExecutionError
from ontoagent.graph.models import SqlStepResult
from ontoagent.llm import FakeChatModel


@pytest.mark.asyncio
async def test_sql_success_execution(monkeypatch):
    """Verify standard SQL generation and execution workflow."""
    fake_model = FakeChatModel()
    fake_model.responses = ["```sql\nSELECT order_id, is_late FROM analytics.fct_orders LIMIT 10;\n```"]

    mock_rows = [
        {"order_id": "ord_100", "is_late": True},
        {"order_id": "ord_101", "is_late": False},
    ]

    async def mock_execute(sql, max_rows=1000):
        return mock_rows

    monkeypatch.setattr("ontoagent.agents.sql.nodes.get_llm", lambda *a, **kw: fake_model)
    monkeypatch.setattr("ontoagent.agents.sql.nodes.execute_ro_query", mock_execute)

    res = await run_sql_instruction("List late orders", role="analyst", use_fake=True)

    assert res.ok is True
    assert res.attempts == 1
    assert len(res.rows) == 2
    assert res.candidate_ids == ["ord_100", "ord_101"]


@pytest.mark.asyncio
async def test_sql_repair_loop_success(monkeypatch):
    """Verify that a syntax error triggers repair loop and succeeds on second attempt."""
    fake_model = FakeChatModel()
    # First response has a syntax error (unclosed parenthesis), second response is valid
    fake_model.responses = [
        "```sql\nSELECT order_id FROM analytics.fct_orders WHERE (is_late LIMIT 10;\n```",
        "```sql\nSELECT order_id FROM analytics.fct_orders WHERE is_late LIMIT 10;\n```",
    ]

    mock_rows = [{"order_id": "ord_200"}]

    async def mock_execute(sql, max_rows=1000):
        return mock_rows

    monkeypatch.setattr("ontoagent.agents.sql.nodes.get_llm", lambda *a, **kw: fake_model)
    monkeypatch.setattr("ontoagent.agents.sql.nodes.execute_ro_query", mock_execute)

    res = await run_sql_instruction("List late orders", role="analyst", use_fake=True, max_repairs=2)

    assert res.ok is True
    assert res.attempts == 2
    assert len(res.rows) == 1


@pytest.mark.asyncio
async def test_security_violation_never_repairs(monkeypatch):
    """Verify that security violations (SEC_*) fail immediately without entering repair loop."""
    fake_model = FakeChatModel()
    # Malicious attempt to query ops schema as analyst
    fake_model.responses = ["```sql\nSELECT * FROM ops.refund_tickets;\n```"]

    monkeypatch.setattr("ontoagent.agents.sql.nodes.get_llm", lambda *a, **kw: fake_model)

    res = await run_sql_instruction("Show me refund tickets", role="analyst", use_fake=True, max_repairs=2)

    assert res.ok is False
    assert res.attempts == 1  # Crucial: exactly 1 attempt, no repair
    assert res.error_code == "SEC_TABLE_DENIED"


@pytest.mark.asyncio
async def test_repair_exhaustion(monkeypatch):
    """Verify that repeatedly failing queries return REPAIR_EXHAUSTED after max_repairs."""
    fake_model = FakeChatModel()
    # Syntax error repeated across all attempts (non-security, so enters repair loop)
    fake_model.responses = [
        "```sql\nSELECT COUNT(*) FROM analytics.fct_orders WHERE (;\n```",
        "```sql\nSELECT COUNT(*) FROM analytics.fct_orders WHERE (;\n```",
        "```sql\nSELECT COUNT(*) FROM analytics.fct_orders WHERE (;\n```",
    ]

    monkeypatch.setattr("ontoagent.agents.sql.nodes.get_llm", lambda *a, **kw: fake_model)

    res = await run_sql_instruction("Show bad data", role="analyst", use_fake=True, max_repairs=2)

    assert res.ok is False
    assert res.attempts == 3  # 1 initial + 2 repairs
    assert res.error_code == "REPAIR_EXHAUSTED"


@pytest.mark.asyncio
async def test_db_unavailable_fails_closed_no_fabricated_rows(monkeypatch):
    """Verify Bug B1: when DB is down and fixtures not requested, fail closed with DB_UNAVAILABLE and no fake rows."""
    fake_model = FakeChatModel()
    fake_model.responses = ["```sql\nSELECT order_id FROM analytics.fct_orders LIMIT 10;\n```"]

    async def mock_execute_failure(sql, max_rows=1000):
        raise DatabaseExecutionError("PostgreSQL connection refused: host is down")

    monkeypatch.delenv("ONTOAGENT_OFFLINE_FIXTURES", raising=False)
    monkeypatch.setattr("ontoagent.agents.sql.nodes.get_llm", lambda *a, **kw: fake_model)
    monkeypatch.setattr("ontoagent.agents.sql.nodes.execute_ro_query", mock_execute_failure)

    res = await run_sql_instruction("Count orders", role="analyst", use_fake=True)

    assert res.ok is False
    assert res.error_code == "DB_UNAVAILABLE"
    assert len(res.rows) == 0
    # Guarantee no fabricated rows exist
    assert "order_000001" not in str(res.rows)
    assert 150.00 not in [r.get("order_value") for r in res.rows]


@pytest.mark.asyncio
async def test_offline_fixtures_explicitly_flagged(monkeypatch):
    """Verify Bug B1: ONTOAGENT_OFFLINE_FIXTURES=1 loads clearly labelled fixture rows with _fixture: True."""
    fake_model = FakeChatModel()
    fake_model.responses = ["```sql\nSELECT order_id FROM analytics.fct_orders LIMIT 10;\n```"]

    async def mock_execute_failure(sql, max_rows=1000):
        raise DatabaseExecutionError("connection timeout expired")

    monkeypatch.setenv("ONTOAGENT_OFFLINE_FIXTURES", "1")
    monkeypatch.setattr("ontoagent.agents.sql.nodes.get_llm", lambda *a, **kw: fake_model)
    monkeypatch.setattr("ontoagent.agents.sql.nodes.execute_ro_query", mock_execute_failure)

    res = await run_sql_instruction("Count orders", role="analyst", use_fake=True)

    assert res.ok is True
    assert len(res.rows) > 0
    # Every row MUST have _fixture: True
    for row in res.rows:
        assert row.get("_fixture") is True


@pytest.mark.asyncio
async def test_candidate_ids_only_from_unmasked_order_id_column(monkeypatch):
    """Verify Bug B6: candidate_ids extracted ONLY when order_id is in query columns, never from masked rows."""
    fake_model = FakeChatModel()
    fake_model.responses = ["```sql\nSELECT delivered_month, COUNT(*) FROM analytics.fct_orders GROUP BY 1;\n```"]

    mock_rows = [{"delivered_month": "2018-08-01", "count": 42}]

    async def mock_execute(sql, max_rows=1000):
        return mock_rows

    monkeypatch.setattr("ontoagent.agents.sql.nodes.get_llm", lambda *a, **kw: fake_model)
    monkeypatch.setattr("ontoagent.agents.sql.nodes.execute_ro_query", mock_execute)

    res = await run_sql_instruction("Monthly trend", role="analyst", use_fake=True)

    assert res.ok is True
    assert res.candidate_ids == []
