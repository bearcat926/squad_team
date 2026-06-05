from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from squad_runtime.agent_contracts import AgentResult
from squad_runtime.agent_registry import AgentRegistry
from squad_runtime.checkpoints import CheckpointManager
from squad_runtime.cli import app as cli_app
from squad_runtime.context import AgentContextBuilder
from squad_runtime.decisions import DecisionDryRun, LeadDecisionChangeSet
from squad_runtime.gate_engine import GateEngine
from squad_runtime.providers import FakeCliProvider
from squad_runtime.runtime import Runtime
from squad_runtime.state import NodeStatus


def test_registry_contains_ten_active_agents_with_versioned_profiles():
    registry = AgentRegistry.default()

    agents = registry.list_agents()

    assert len(agents) == 10
    assert registry.version == "registry-v1"
    assert registry.get("squad-lead").output_contract == "LeadDecisionChangeSet"
    assert registry.get("frontend-developer").output_contract == "AgentResult"
    assert registry.get("reality-checker").role == "Release readiness and veto"


def test_decision_dry_run_rejects_unknown_owner_and_done_node_mutation(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("dry run")
    done_node = runtime.create_node(run.id, "Finished", "frontend", "frontend-developer")
    runtime.transition_node(done_node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    runtime.transition_node(done_node.id, NodeStatus.READY, NodeStatus.RUNNING, "dispatch")
    runtime.transition_node(done_node.id, NodeStatus.RUNNING, NodeStatus.PASS, "pass")
    runtime.transition_node(done_node.id, NodeStatus.PASS, NodeStatus.DONE, "closed")

    unknown_owner = LeadDecisionChangeSet(
        operations=[
            {
                "op": "create_node",
                "title": "Bad owner",
                "nodeType": "frontend",
                "ownerAgentId": "missing-agent",
            }
        ]
    )
    mutate_done = LeadDecisionChangeSet(operations=[{"op": "mark_stale", "nodeId": done_node.id, "reason": "rewrite"}])

    registry = AgentRegistry.default()
    assert DecisionDryRun(runtime, registry).validate(run.id, unknown_owner).accepted is False
    rejected = DecisionDryRun(runtime, registry).validate(run.id, mutate_done)
    assert rejected.accepted is False
    assert "done_node_protected" in rejected.errors
    assert runtime.events.query(run.id).events[-1].type == "decision_rejected"


def test_snapshot_checkpoint_is_content_addressed_and_reproducible(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (project / ".squad").mkdir()
    (project / ".squad" / "token").write_text("secret", encoding="utf-8")

    manager = CheckpointManager(project, project / ".squad")
    first = manager.create_snapshot_checkpoint()
    second = manager.create_snapshot_checkpoint()

    assert first.checkpoint_id == second.checkpoint_id
    assert first.mode == "snapshot"
    manifest_path = project / ".squad" / "checkpoints" / first.checkpoint_id / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [item["path"] for item in manifest["files"]] == ["app.py"]


def test_context_bundle_is_role_scoped_and_excludes_raw_outputs(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("context")
    backend_node = runtime.create_node(run.id, "Define API", "backend", "backend-architect", checkpoint_id="ckp-ctx")
    node = runtime.create_node(run.id, "Build UI", "frontend", "frontend-developer", checkpoint_id="ckp-ctx")
    runtime.record_event(run.id, "verification_result", {"coveragePercent": 91.0, "testsDirectoryExists": True})
    runtime.persist_agent_result(
        AgentResult(
            taskNodeId=backend_node.id,
            agentId="backend-architect",
            status="pass",
            summary="Backend contract ready",
            evidence=[{"type": "api", "content": "GET /alerts"}],
            artifacts=[{"name": "api-contract", "path": "api-contract.json"}],
            risks=[],
            nextActions=[],
            confidence=0.9,
            workedAgainstCheckpoint="ckp-ctx",
            agentContractVersion="v1",
        ),
        provider_used="fake_cli",
    )

    bundle = AgentContextBuilder(runtime, AgentRegistry.default()).build(node.id)

    assert bundle.agent_id == "frontend-developer"
    assert bundle.output_contract == "AgentResult"
    assert ".squad/*" in bundle.forbidden_paths
    assert bundle.runtime_facts[0]["type"] == "verification_result"
    assert bundle.runtime_facts[0]["payload"]["coveragePercent"] == 91.0
    assert bundle.dependency_summaries[0]["output_summary"] == "Backend contract ready"
    assert "raw_stdout" not in bundle.dependency_summaries[0]


def test_lead_dispatch_context_uses_agent_result_contract(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("lead context")
    node = runtime.create_node(run.id, "Lead acceptance", "lead", "squad-lead", checkpoint_id="ckp-lead")

    bundle = AgentContextBuilder(runtime, AgentRegistry.default()).build(node.id)

    assert AgentRegistry.default().get("squad-lead").output_contract == "LeadDecisionChangeSet"
    assert bundle.output_contract == "AgentResult"


def test_fake_provider_dispatch_persists_agent_result_and_typed_events(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("dispatch")
    node = runtime.create_node(run.id, "Test", "test", "test-engineer", checkpoint_id="ckp-1")
    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")

    provider = FakeCliProvider()
    result = provider.execute(runtime, node, AgentRegistry.default().get("test-engineer"))

    assert result.status == "pass"
    assert runtime.get_node(node.id).status == NodeStatus.PASS
    event_types = [event.type for event in runtime.events.query(run.id).events]
    assert "llm_session_started" in event_types
    assert "agent_result_submitted" in event_types
    assert runtime.list_agent_results(run.id)[0]["providerUsed"] == "fake_cli"


def test_gate_engine_uses_fact_tables_not_forged_events(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("facts only")
    runtime.record_event(run.id, "agent_result_submitted", {"taskNodeId": "forged-node", "agentId": "test-engineer", "status": "pass"})

    forged = GateEngine(runtime).evaluate_all(run.id)

    assert forged["test_gate"].status != "pass"

    test_node = runtime.create_node(run.id, "Tests", "test", "test-engineer")
    review_node = runtime.create_node(run.id, "Review", "review", "code-reviewer")
    reality_node = runtime.create_node(run.id, "Reality", "gate", "reality-checker")
    for node, agent_id in [
        (test_node, "test-engineer"),
        (review_node, "code-reviewer"),
        (reality_node, "reality-checker"),
    ]:
        runtime.persist_agent_result(
            AgentResult(
                taskNodeId=node.id,
                agentId=agent_id,
                status="pass",
                summary=f"{agent_id} pass",
                evidence=[],
                artifacts=[],
                risks=[],
                nextActions=[],
                confidence=0.9,
                workedAgainstCheckpoint=node.checkpoint_id,
                agentContractVersion="v1",
            ),
            provider_used="fake_cli",
        )

    gates = GateEngine(runtime).evaluate_all(run.id, trigger="test")

    assert gates["release_gate"].status == "pass"
    gate_events = [event for event in runtime.events.query(run.id).events if event.type == "gate_decision"]
    assert gate_events


def test_cli_agents_doctor_and_eval_gates(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert runner.invoke(cli_app, ["init"]).exit_code == 0
        listed = runner.invoke(cli_app, ["agents", "list"])
        assert listed.exit_code == 0
        assert "squad-lead" in listed.stdout

        doctor = runner.invoke(cli_app, ["agents", "doctor"])
        assert doctor.exit_code == 0
        assert "fake_cli" in doctor.stdout

        run_result = runner.invoke(cli_app, ["run", "gate cli"])
        run_id = json.loads(run_result.stdout)["id"]
        eval_result = runner.invoke(cli_app, ["eval-gates", run_id])
        assert eval_result.exit_code == 0
        assert "release_gate" in eval_result.stdout
