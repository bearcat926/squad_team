from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.acceptance.run_real_llm_acceptance import AcceptanceScenarioRunner, DispatchOutcome
from squad_runtime.acceptance import AcceptanceReporter
from squad_runtime.agent_contracts import AgentResult
from squad_runtime.agent_registry import AgentRegistry
from squad_runtime.gate_engine import GateEngine
from squad_runtime.providers import FakeCliProvider, ProviderRegistry
from squad_runtime.runtime import Runtime
from squad_runtime.state import NodeStatus


class BlockingProvider(FakeCliProvider):
    def __init__(self, blocked_agent_id: str):
        self.blocked_agent_id = blocked_agent_id

    def execute(self, runtime: Runtime, node, profile, synthetic: bool = False, provider_fallback_triggered: bool = False, fallback_reason: str | None = None):
        if profile.agent_id != self.blocked_agent_id:
            return super().execute(runtime, node, profile, synthetic, provider_fallback_triggered, fallback_reason)
        current = runtime.get_node(node.id)
        if current.status == NodeStatus.READY:
            runtime.transition_node(current.id, NodeStatus.READY, NodeStatus.RUNNING, "blocking provider dispatch")
        runtime.transition_node(
            node.id,
            NodeStatus.RUNNING,
            NodeStatus.BLOCKED,
            "test provider blocked",
            blocked_reason_code="invalid_agent_result",
        )
        runtime.events.append(
            node.run_id,
            "invalid_agent_result",
            {"nodeId": node.id, "agentId": profile.agent_id, "reason": "test_block"},
            critical=True,
        )
        return None


class VerifiedPassProvider(FakeCliProvider):
    name = "claude_cli"

    def execute(self, runtime: Runtime, node, profile, synthetic: bool = False, provider_fallback_triggered: bool = False, fallback_reason: str | None = None):
        result = super().execute(runtime, node, profile, synthetic, provider_fallback_triggered, fallback_reason)
        stored = runtime.list_agent_results(node.run_id)[-1]
        with runtime.conn:
            runtime.conn.execute(
                """
                UPDATE agent_results
                SET provider_used = ?, provider_type = ?, provider_identity_verified = ?
                WHERE id = ?
                """,
                ("claude_cli", "real_llm", 1, stored["id"]),
            )
        return result


class RateLimitedThenPassProvider(VerifiedPassProvider):
    def __init__(self) -> None:
        self.attempts: dict[str, int] = {}

    def execute(self, runtime: Runtime, node, profile, synthetic: bool = False, provider_fallback_triggered: bool = False, fallback_reason: str | None = None):
        attempts = self.attempts.get(node.id, 0) + 1
        self.attempts[node.id] = attempts
        if attempts == 1:
            current = runtime.get_node(node.id)
            if current.status == NodeStatus.READY:
                runtime.transition_node(current.id, NodeStatus.READY, NodeStatus.RUNNING, "rate limited provider dispatch")
            runtime.transition_node(node.id, NodeStatus.RUNNING, NodeStatus.AGENT_UNAVAILABLE, "provider rate limited")
            payload = {
                "nodeId": node.id,
                "agentId": profile.agent_id,
                "provider": "claude_cli",
                "statusCode": 429,
                "retryAfterSeconds": 0,
            }
            runtime.events.append(node.run_id, "provider_rate_limited", payload, critical=True)
            runtime.events.append(node.run_id, "provider_blocked", {**payload, "detail": "429"}, critical=True)
            return None
        return super().execute(runtime, node, profile, synthetic, provider_fallback_triggered, fallback_reason)


class AlwaysRateLimitedProvider(RateLimitedThenPassProvider):
    def execute(self, runtime: Runtime, node, profile, synthetic: bool = False, provider_fallback_triggered: bool = False, fallback_reason: str | None = None):
        current = runtime.get_node(node.id)
        if current.status == NodeStatus.READY:
            runtime.transition_node(current.id, NodeStatus.READY, NodeStatus.RUNNING, "rate limited provider dispatch")
        runtime.transition_node(node.id, NodeStatus.RUNNING, NodeStatus.AGENT_UNAVAILABLE, "provider rate limited")
        payload = {
            "nodeId": node.id,
            "agentId": profile.agent_id,
            "provider": "claude_cli",
            "statusCode": 429,
            "retryAfterSeconds": 0,
        }
        runtime.events.append(node.run_id, "provider_rate_limited", payload, critical=True)
        runtime.events.append(node.run_id, "provider_blocked", {**payload, "detail": "429"}, critical=True)
        return None


def _codebase_memory_ok() -> dict:
    return {
        "status": "indexed",
        "project": "E-Project-squad-runtime-index-mirror",
        "nodes": 1,
        "edges": 1,
        "architecture": "ok",
    }


def _write_coverage_baseline(runtime: Runtime, total_percent: float = 90.0) -> None:
    acceptance_dir = runtime.squad_dir / "acceptance"
    acceptance_dir.mkdir(parents=True, exist_ok=True)
    (acceptance_dir / "coverage-baseline.json").write_text(
        json.dumps({"total_percent": total_percent}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_full_team_refuses_to_start_when_minimal_preflight_fails(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    _write_coverage_baseline(runtime)
    runner = AcceptanceScenarioRunner(
        runtime=runtime,
        registry=AgentRegistry.default(),
        providers=ProviderRegistry({"claude_cli": BlockingProvider("frontend-developer")}),
        provider_name="claude_cli",
        acceptance_root=tmp_path,
        coverage_percent=90.0,
        codebase_memory=_codebase_memory_ok(),
    )

    with pytest.raises(RuntimeError, match="minimal preflight"):
        runner.run_full_team()

    runs = runtime.list_runs()
    assert len(runs) == 1
    assert "minimal" in runs[0].goal


def test_full_team_delays_git_workflow_until_release_gate_pass(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    _write_coverage_baseline(runtime)
    runner = AcceptanceScenarioRunner(
        runtime=runtime,
        registry=AgentRegistry.default(),
        providers=ProviderRegistry({"claude_cli": VerifiedPassProvider()}),
        provider_name="claude_cli",
        acceptance_root=tmp_path,
        coverage_percent=90.0,
        codebase_memory=_codebase_memory_ok(),
    )

    result = runner.run_full_team()

    nodes = runtime.list_nodes(result.run_id)
    git_node = next(node for node in nodes if node.owner_agent_id == "git-workflow-master")
    gate_events = [event for event in runtime.events.query(result.run_id, limit=100000).events if event.type == "gate_decision"]
    git_start = next(
        event
        for event in runtime.events.query(result.run_id, limit=100000).events
        if event.type == "llm_session_started" and event.payload.get("agentId") == "git-workflow-master"
    )
    release_pass = next(event for event in gate_events if event.payload.get("gateName") == "release_gate" and event.payload.get("status") == "pass")

    assert git_node.status == NodeStatus.PASS
    assert release_pass.sequence_number < git_start.sequence_number


def test_required_downstream_node_is_dependency_blocked_after_upstream_failure(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    _write_coverage_baseline(runtime)
    runner = AcceptanceScenarioRunner(
        runtime=runtime,
        registry=AgentRegistry.default(),
        providers=ProviderRegistry({"claude_cli": BlockingProvider("backend-architect")}),
        provider_name="claude_cli",
        acceptance_root=tmp_path,
        coverage_percent=90.0,
        codebase_memory=_codebase_memory_ok(),
    )

    result = runner.run_minimal(implementation_agent_id="backend-architect")

    nodes = runtime.list_nodes(result.run_id)
    test_node = next(node for node in nodes if node.owner_agent_id == "test-engineer")
    event_types = [event.type for event in runtime.events.query(result.run_id, limit=100000).events]
    outcomes = [entry["outcome"] for entry in result.dispatch_records]

    assert test_node.status == NodeStatus.BLOCKED
    assert test_node.blocked_reason_code == "gate_dependency_failed"
    assert "dependency_blocked" in event_types
    assert DispatchOutcome.DEPENDENCY_BLOCKED.value in outcomes


def test_runner_retries_provider_rate_limited_node_once_and_records_success(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    _write_coverage_baseline(runtime)
    provider = RateLimitedThenPassProvider()
    runner = AcceptanceScenarioRunner(
        runtime=runtime,
        registry=AgentRegistry.default(),
        providers=ProviderRegistry({"claude_cli": provider}),
        provider_name="claude_cli",
        acceptance_root=tmp_path,
        coverage_percent=90.0,
        codebase_memory=_codebase_memory_ok(),
    )

    result = runner.run_minimal()

    lead_node = next(node for node in runtime.list_nodes(result.run_id) if node.owner_agent_id == "squad-lead")
    event_types = [event.type for event in runtime.events.query(result.run_id, limit=100000).events]
    lead_record = next(record for record in result.dispatch_records if record["agentId"] == "squad-lead")
    assert provider.attempts[lead_node.id] == 2
    assert lead_record["outcome"] == DispatchOutcome.PASS.value
    assert lead_record["rateLimitRetries"] == 1
    assert "provider_rate_limited" in event_types
    assert "provider_rate_limit_retry" in event_types


def test_runner_fails_provider_rate_limited_node_after_retry_limit(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    _write_coverage_baseline(runtime)
    runner = AcceptanceScenarioRunner(
        runtime=runtime,
        registry=AgentRegistry.default(),
        providers=ProviderRegistry({"claude_cli": AlwaysRateLimitedProvider()}),
        provider_name="claude_cli",
        acceptance_root=tmp_path,
        coverage_percent=90.0,
        codebase_memory=_codebase_memory_ok(),
    )

    result = runner.run_minimal()

    lead_record = next(record for record in result.dispatch_records if record["agentId"] == "squad-lead")
    assert lead_record["outcome"] == DispatchOutcome.UNAVAILABLE.value
    assert lead_record["rateLimitRetries"] == 1
    assert result.conclusion == "FAIL"


def test_acceptance_report_fails_when_required_node_is_not_terminal(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("non terminal report")
    runtime.create_node(run.id, "Ready but not done", "test", "test-engineer")

    payload = AcceptanceReporter(runtime).write_report(
        run.id,
        tmp_path / "acceptance.md",
        coverage_percent=90.0,
        codebase_memory=_codebase_memory_ok(),
    )

    assert payload["conclusion"] == "FAIL"
    assert "required_node_not_terminal:test-engineer" in payload["risks"]


def test_first_coverage_baseline_creation_blocks_formal_pass(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("coverage baseline")
    for agent in AgentRegistry.default().list_agents():
        node = runtime.create_node(run.id, agent.agent_id, "test", agent.agent_id, checkpoint_id="ckp")
        runtime.persist_agent_result(
            AgentResult(
                taskNodeId=node.id,
                agentId=agent.agent_id,
                status="pass",
                summary="pass",
                evidence=[],
                artifacts=[],
                risks=[],
                nextActions=[],
                confidence=0.9,
                workedAgainstCheckpoint="ckp",
                agentContractVersion="v1",
            ),
            provider_used="claude_cli",
            provider_type="real_llm",
            provider_identity_verified=True,
        )
    GateEngine(runtime).evaluate_all(run.id)

    payload = AcceptanceReporter(runtime).write_report(
        run.id,
        tmp_path / "acceptance.md",
        coverage_percent=90.0,
        codebase_memory=_codebase_memory_ok(),
    )

    assert payload["coverage_baseline_created"] is True
    assert payload["conclusion"] == "FAIL"
    assert "coverage_baseline_created_requires_rerun" in payload["risks"]


def test_export_log_contains_fact_tables(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("fact export")
    node = runtime.create_node(run.id, "Review", "review", "code-reviewer", checkpoint_id="ckp")
    runtime.persist_agent_result(
        AgentResult(
            taskNodeId=node.id,
            agentId="code-reviewer",
            status="pass",
            summary="reviewed",
            evidence=[{"type": "review", "content": "approved"}],
            artifacts=[{"name": "review-note", "path": "reports/review.md", "type": "report"}],
            risks=[],
            nextActions=[],
            confidence=0.9,
            workedAgainstCheckpoint="ckp",
            agentContractVersion="v1",
        ),
        provider_used="claude_cli",
        provider_type="real_llm",
        provider_identity_verified=True,
    )
    runtime.create_review_finding(run.id, node.id, "code-reviewer", "P2", "minor issue")

    output = tmp_path / "FULL_DATA_LOG.json"
    runtime.export_run_log(run.id, output, include_export_event=True)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["agentResults"]
    assert payload["evidenceItems"]
    assert payload["reviewFindings"]
    assert payload["artifacts"]
