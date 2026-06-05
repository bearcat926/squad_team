"""Tests for the AnalyticsEngine."""

from __future__ import annotations

from pathlib import Path

from squad_runtime.agent_contracts import AgentResult
from squad_runtime.analytics import AnalyticsEngine
from squad_runtime.runtime import Runtime


def test_empty_run_returns_zero_counts(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("empty analytics")

    summary = AnalyticsEngine(runtime).compute_summary(run.id)

    assert summary["run_count"] == 1
    assert summary["result_count"] == 0
    assert summary["success_rate"] == 0.0


def test_run_with_results_computes_rates(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("analytics run")

    # Create two passing nodes
    for i, agent_id in enumerate(["backend-architect", "frontend-developer"]):
        node = runtime.create_node(run.id, f"Task {i}", "backend", agent_id)
        runtime.persist_agent_result(
            AgentResult(
                taskNodeId=node.id,
                agentId=agent_id,
                status="pass",
                summary=f"{agent_id} done",
                evidence=[],
                artifacts=[],
                risks=[],
                nextActions=[],
                confidence=0.9,
                workedAgainstCheckpoint=node.checkpoint_id,
                agentContractVersion="v1",
            ),
            provider_used="claude_cli",
            provider_type="real_llm",
            provider_identity_verified=True,
        )

    summary = AnalyticsEngine(runtime).compute_summary(run.id)

    assert summary["result_count"] == 2
    assert summary["success_rate"] == 100.0
    assert summary["avg_confidence"] == 0.9
    assert summary["provider_usage"]["claude_cli"] == 2


def test_provider_usage_aggregation(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("provider analytics")

    for i, (provider, agent_id) in enumerate(
        [
            ("claude_cli", "backend-architect"),
            ("fake_cli", "frontend-developer"),
            ("claude_cli", "test-engineer"),
        ]
    ):
        node = runtime.create_node(run.id, f"Task {i}", "backend", agent_id)
        runtime.persist_agent_result(
            AgentResult(
                taskNodeId=node.id,
                agentId=agent_id,
                status="pass",
                summary="done",
                evidence=[],
                artifacts=[],
                risks=[],
                nextActions=[],
                confidence=0.8,
                workedAgainstCheckpoint=node.checkpoint_id,
                agentContractVersion="v1",
            ),
            provider_used=provider,
        )

    summary = AnalyticsEngine(runtime).compute_summary(run.id)

    assert summary["provider_usage"]["claude_cli"] == 2
    assert summary["provider_usage"]["fake_cli"] == 1


def test_global_summary_across_runs(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    for i in range(3):
        runtime.create_run(f"run {i}")

    summary = AnalyticsEngine(runtime).compute_summary()

    assert summary["run_count"] == 3
