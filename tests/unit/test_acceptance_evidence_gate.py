from __future__ import annotations

from pathlib import Path

from squad_runtime.acceptance import AcceptanceReporter
from squad_runtime.agent_contracts import AgentResult
from squad_runtime.runtime import Runtime
from squad_runtime.state import NodeStatus


def test_acceptance_report_fails_when_evidence_gate_fails_even_if_runtime_gates_pass(tmp_path: Path) -> None:
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("full dev evidence gate")
    node = runtime.create_node(run.id, "Lead", "lead", "squad-lead", checkpoint_id="ckp-1")
    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    runtime.transition_node(node.id, NodeStatus.READY, NodeStatus.RUNNING, "running")
    runtime.transition_node(node.id, NodeStatus.RUNNING, NodeStatus.PASS, "pass")
    runtime.persist_agent_result(
        AgentResult(
            taskNodeId=node.id,
            agentId="squad-lead",
            status="pass",
            summary="pass without artifacts",
            evidence=[{"type": "plan", "content": "plan"}],
            artifacts=[],
            risks=[],
            nextActions=[],
            confidence=0.9,
            workedAgainstCheckpoint="ckp-1",
            agentContractVersion="v1",
        ),
        provider_used="claude_cli",
        provider_type="real_llm",
        provider_identity_verified=True,
    )
    for gate_name in ["test_gate", "code_review_gate", "reality_checker_gate", "release_gate"]:
        runtime.upsert_gate_state(run.id, gate_name, "pass", "legacy pass")

    payload = AcceptanceReporter(runtime).write_report(
        run.id,
        tmp_path / "acceptance-report.md",
        coverage_percent=99.0,
        codebase_memory={"status": "indexed", "architecture": {"packages": []}},
        required_agent_ids=["squad-lead"],
        scenario_type="full_dev",
    )

    assert payload["conclusion"] == "FAIL"
    assert payload["evidence_gate"]["status"] == "fail"
    assert "evidence_gate_failed" in payload["risks"]
    assert payload["resolved_profile_hash"] == payload["evidence_gate"]["resolvedProfileHash"]
