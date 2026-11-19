"""Unit tests for the evaluation runner.

Verifies that evals/eval_runner.py executes offline without network or service crashes
using FakeChatModel.
"""

from pathlib import Path
import pytest
from evals.eval_runner import run_evaluation


@pytest.mark.asyncio
async def test_eval_runner_offline_smoke(monkeypatch, tmp_path):
    """Run fast 3-question smoke evaluation offline with FakeChatModel."""
    monkeypatch.setenv("ONTOAGENT_FAKE_LLM", "1")

    # Run evaluation with subset of 3 items
    report = await run_evaluation(
        golden_path=Path("evals/golden.jsonl"),
        suite="all",
        subset=3,
        no_cache=True,
    )

    assert report["total_evaluated"] == 3
    assert "latency_p50_ms" in report
    assert "routing_accuracy" in report
    assert len(report["results"]) == 3
    for r in report["results"]:
        assert "id" in r
        assert "passed" in r
        assert "latency_ms" in r
