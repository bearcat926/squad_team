from __future__ import annotations

from pathlib import Path

from squad_runtime.agent_contracts import AgentResult
from squad_runtime.gate_engine import GateEngine
from squad_runtime.runtime import Runtime


def persist_pass(runtime: Runtime, run_id: str, agent_id: str, node_type: str = "test") -> None:
    node = runtime.create_node(run_id, agent_id, node_type, agent_id, checkpoint_id="ckp")
    runtime.persist_agent_result(
        AgentResult(
            taskNodeId=node.id,
            agentId=agent_id,
            status="pass",
            summary=f"{agent_id} pass",
            evidence=[{"type": "agent", "content": "pass"}],
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


def test_strict_test_gate_fails_agent_result_pass_without_test_artifact(tmp_path: Path) -> None:
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("strict")
    persist_pass(runtime, run.id, "test-engineer", "test")

    decisions = GateEngine(runtime).evaluate_all(run.id, mode="strict")

    assert decisions["test_gate"].status == "fail"
    assert decisions["test_gate"].blocked_reason_code == "evidence_missing"
    assert decisions["test_gate"].details["failureClass"] == "EVIDENCE_MISSING"


def test_strict_provider_authenticity_gate_fails_tampered_identity(tmp_path: Path) -> None:
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("strict")
    node = runtime.create_node(run.id, "Test", "test", "test-engineer", checkpoint_id="ckp")
    runtime.persist_agent_result(
        AgentResult(
            taskNodeId=node.id,
            agentId="test-engineer",
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
        provider_used="fake_cli",
        provider_type="deterministic",
        provider_identity_verified=False,
        synthetic=True,
    )

    decisions = GateEngine(runtime).evaluate_all(run.id, mode="strict")

    assert decisions["provider_authenticity_gate"].status == "fail"
    assert decisions["provider_authenticity_gate"].details["failureClass"] == "PROVIDER_FAILURE"
    assert decisions["release_gate"].status == "blocked"


def test_strict_gates_pass_when_fact_chain_is_complete(tmp_path: Path) -> None:
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("strict")
    persist_pass(runtime, run.id, "test-engineer", "test")
    persist_pass(runtime, run.id, "code-reviewer", "review")
    persist_pass(runtime, run.id, "reality-checker", "gate")
    for event_type, payload in [
        ("artifact_produced", {"name": "test-report", "path": "reports/test.md", "type": "test", "purpose": "test_evidence"}),
        ("artifact_produced", {"name": "review-fact", "path": "reports/review.md", "type": "review_fact", "purpose": "code_review"}),
        ("artifact_produced", {"name": "release-archive", "path": "release/archive.json", "type": "release_archive", "purpose": "release"}),
        ("verification_result", {"kind": "ui_smoke", "status": "pass"}),
        ("verification_result", {"kind": "coverage", "status": "pass", "evidenceStrength": "high"}),
        ("event_hash_chain_sealed", {"finalEventHash": "sha256:event"}),
        ("runtime_chain_graph_sealed", {"chainGraphHash": "sha256:chain", "chainBuilderVersion": "chain-builder/v1"}),
    ]:
        runtime.record_event(run.id, event_type, payload)

    decisions = GateEngine(runtime).evaluate_all(run.id, mode="strict")

    assert {name: decision.status for name, decision in decisions.items()} == {
        "test_gate": "pass",
        "code_review_gate": "pass",
        "provider_authenticity_gate": "pass",
        "evidence_authenticity_gate": "pass",
        "coverage_gate": "pass",
        "chain_completeness_gate": "pass",
        "boundary_gate": "pass",
        "reality_checker_gate": "pass",
        "release_gate": "pass",
    }
