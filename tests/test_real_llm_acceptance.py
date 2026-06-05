from __future__ import annotations

import json
import sys
from pathlib import Path

from squad_runtime.acceptance import AcceptanceReporter
from squad_runtime.agent_contracts import AgentResult
from squad_runtime.agent_registry import AgentRegistry
from squad_runtime.gate_engine import GateEngine
from squad_runtime.providers import LocalCliProvider
from squad_runtime.runtime import Runtime
from squad_runtime.state import NodeStatus


def _write_script(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def _agent_result_payload(node_id: str, agent_id: str, checkpoint: str) -> dict:
    return {
        "taskNodeId": node_id,
        "agentId": agent_id,
        "status": "pass",
        "summary": "real provider pass",
        "evidence": [{"type": "real_llm", "content": "structured evidence"}],
        "artifacts": [],
        "risks": [],
        "nextActions": [],
        "confidence": 0.9,
        "workedAgainstCheckpoint": checkpoint,
        "agentContractVersion": "v1",
    }


def test_local_cli_provider_prefers_final_result_json_and_persists_verified_identity(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("real provider")
    node = runtime.create_node(run.id, "Build UI", "frontend", "frontend-developer", checkpoint_id="ckp-real")
    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    script = _write_script(
        tmp_path / "provider_success.py",
        """
import json, os
payload = json.loads(os.environ['SQUAD_TEST_AGENT_RESULT'])
with open(os.environ['SQUAD_FINAL_RESULT_PATH'], 'w', encoding='utf-8') as fh:
    json.dump(payload, fh)
print('ignored stdout')
""".strip(),
    )
    provider = LocalCliProvider(
        "claude_cli",
        sys.executable,
        command_args=[str(script)],
        provider_type="real_llm",
        identity_verified=False,
    )
    provider.extra_env = {"SQUAD_TEST_AGENT_RESULT": json.dumps(_agent_result_payload(node.id, "frontend-developer", "ckp-real"))}

    result = provider.execute(runtime, node, AgentRegistry.default().get("frontend-developer"))

    assert result.status == "pass"
    stored = runtime.list_agent_results(run.id)[0]
    assert stored["providerUsed"] == "claude_cli"
    assert stored["providerType"] == "real_llm"
    assert stored["providerIdentityVerified"] is True
    dispatch_dir = tmp_path / ".squad" / "runs" / run.id / "dispatches"
    assert list(dispatch_dir.glob("*/context.json"))
    prompt_path = list(dispatch_dir.glob("*/prompt.md"))[0]
    prompt = prompt_path.read_text(encoding="utf-8")
    assert f'"taskNodeId": "{node.id}"' in prompt
    assert '"workedAgainstCheckpoint": "ckp-real"' in prompt
    assert "Runtime Output Contract: AgentResult" in prompt
    assert list(dispatch_dir.glob("*/agent-result.schema.json"))
    assert list(dispatch_dir.glob("*/final-result.json"))


def test_local_cli_provider_default_command_forces_json_output_and_isolated_session():
    provider = LocalCliProvider("claude_cli", "claude")

    command = provider._command("Return JSON")

    assert "--bare" in command
    assert "--disable-slash-commands" in command
    assert "--system-prompt" in command
    assert "JSON-only API" in " ".join(command)
    assert "--output-format" in command
    assert "json" in command
    assert "--no-session-persistence" in command
    assert "Return JSON" not in command


def test_local_cli_provider_default_timeout_allows_real_llm_acceptance():
    provider = LocalCliProvider("claude_cli", "claude")

    assert provider.timeout_sec == 600


def test_local_cli_provider_prompt_uses_agent_result_contract_for_squad_lead(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("lead prompt")
    node = runtime.create_node(run.id, "Lead planning", "lead", "squad-lead", checkpoint_id="ckp-lead")
    runtime.record_event(run.id, "verification_result", {"coveragePercent": 91.0})
    context = __import__("squad_runtime.context", fromlist=["AgentContextBuilder"]).AgentContextBuilder(runtime, AgentRegistry.default()).build(node.id)
    prompt = LocalCliProvider("claude_cli", "claude")._build_prompt(context)

    assert "Runtime Output Contract: AgentResult" in prompt
    assert "Output Contract: LeadDecisionChangeSet" not in prompt
    assert "Do not ask for more context" in prompt
    assert "Do not inspect files" in prompt
    assert "Runtime facts available" in prompt
    assert "coveragePercent" in prompt
    assert "Prior dependency summaries" in prompt


def test_local_cli_provider_rejects_stdout_with_multiple_json_objects(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("bad stdout")
    node = runtime.create_node(run.id, "Build UI", "frontend", "frontend-developer", checkpoint_id="ckp-real")
    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    script = _write_script(tmp_path / "provider_bad_stdout.py", "print('{\\\"a\\\":1}{\\\"b\\\":2}')")
    provider = LocalCliProvider("claude_cli", sys.executable, command_args=[str(script)], provider_type="real_llm", identity_verified=True)

    outcome = provider.execute(runtime, node, AgentRegistry.default().get("frontend-developer"))

    assert outcome is None
    updated = runtime.get_node(node.id)
    assert updated.status == NodeStatus.BLOCKED
    assert updated.blocked_reason_code == "invalid_agent_result"
    assert runtime.list_agent_results(run.id) == []


def test_local_cli_provider_accepts_single_json_object_with_surrounding_prose(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("prose stdout")
    node = runtime.create_node(run.id, "Build UI", "frontend", "frontend-developer", checkpoint_id="ckp-real")
    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    payload = json.dumps(_agent_result_payload(node.id, "frontend-developer", "ckp-real"))
    stdout = f"I will return JSON now.\n{payload}\nDone."
    script = _write_script(
        tmp_path / "provider_prose_stdout.py",
        f"print({stdout!r})",
    )
    provider = LocalCliProvider("claude_cli", sys.executable, command_args=[str(script)], provider_type="real_llm", identity_verified=True)

    outcome = provider.execute(runtime, node, AgentRegistry.default().get("frontend-developer"))

    assert outcome is not None
    assert outcome.status == "pass"
    assert runtime.get_node(node.id).status == NodeStatus.PASS


def test_local_cli_provider_accepts_single_markdown_fenced_json_object(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("fenced stdout")
    node = runtime.create_node(run.id, "Build UI", "frontend", "frontend-developer", checkpoint_id="ckp-real")
    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    payload = json.dumps(_agent_result_payload(node.id, "frontend-developer", "ckp-real"))
    stdout = f"```json\n{payload}\n```"
    script = _write_script(
        tmp_path / "provider_fenced_stdout.py",
        f"print({stdout!r})",
    )
    provider = LocalCliProvider("claude_cli", sys.executable, command_args=[str(script)], provider_type="real_llm", identity_verified=True)

    outcome = provider.execute(runtime, node, AgentRegistry.default().get("frontend-developer"))

    assert outcome is not None
    assert outcome.status == "pass"
    assert runtime.get_node(node.id).status == NodeStatus.PASS


def test_local_cli_provider_accepts_claude_json_wrapper_stdout(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("wrapper stdout")
    node = runtime.create_node(run.id, "Build UI", "frontend", "frontend-developer", checkpoint_id="ckp-real")
    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    payload = json.dumps(_agent_result_payload(node.id, "frontend-developer", "ckp-real"))
    wrapper = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": payload})
    script = _write_script(
        tmp_path / "provider_wrapper_stdout.py",
        f"print({wrapper!r})",
    )
    provider = LocalCliProvider("claude_cli", sys.executable, command_args=[str(script)], provider_type="real_llm", identity_verified=True)

    outcome = provider.execute(runtime, node, AgentRegistry.default().get("frontend-developer"))

    assert outcome is not None
    assert outcome.status == "pass"
    assert runtime.get_node(node.id).status == NodeStatus.PASS


def test_local_cli_provider_checkpoint_mismatch_blocks_with_dedicated_reason(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("checkpoint")
    node = runtime.create_node(run.id, "Build UI", "frontend", "frontend-developer", checkpoint_id="ckp-current")
    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    script = _write_script(
        tmp_path / "provider_mismatch.py",
        """
import json, os
payload = json.loads(os.environ['SQUAD_TEST_AGENT_RESULT'])
with open(os.environ['SQUAD_FINAL_RESULT_PATH'], 'w', encoding='utf-8') as fh:
    json.dump(payload, fh)
""".strip(),
    )
    provider = LocalCliProvider("claude_cli", sys.executable, command_args=[str(script)], provider_type="real_llm", identity_verified=True)
    provider.extra_env = {"SQUAD_TEST_AGENT_RESULT": json.dumps(_agent_result_payload(node.id, "frontend-developer", "ckp-old"))}

    outcome = provider.execute(runtime, node, AgentRegistry.default().get("frontend-developer"))

    assert outcome is None
    updated = runtime.get_node(node.id)
    assert updated.status == NodeStatus.BLOCKED
    assert updated.blocked_reason_code == "checkpoint_mismatch"
    assert any(event.type == "checkpoint_mismatch" for event in runtime.events.query(run.id).events)


def test_local_cli_provider_timeout_marks_agent_unavailable_and_keeps_artifacts(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("timeout")
    node = runtime.create_node(run.id, "Build UI", "frontend", "frontend-developer")
    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    script = _write_script(tmp_path / "provider_timeout.py", "import time; time.sleep(5)")
    provider = LocalCliProvider("claude_cli", sys.executable, command_args=[str(script)], provider_type="real_llm", identity_verified=True, timeout_sec=0.2)

    outcome = provider.execute(runtime, node, AgentRegistry.default().get("frontend-developer"))

    assert outcome is None
    assert runtime.get_node(node.id).status == NodeStatus.AGENT_UNAVAILABLE
    assert any(event.type == "agent_timeout" for event in runtime.events.query(run.id).events)
    dispatch_dirs = list((tmp_path / ".squad" / "runs" / run.id / "dispatches").glob("*"))
    assert dispatch_dirs
    assert (dispatch_dirs[0] / "timeout.json").exists()


def test_local_cli_provider_unavailable_records_provider_blocked(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("provider unavailable")
    node = runtime.create_node(run.id, "Build UI", "frontend", "frontend-developer")
    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    provider = LocalCliProvider("claude_cli", "definitely-missing-squad-provider")

    outcome = provider.execute(runtime, node, AgentRegistry.default().get("frontend-developer"))

    assert outcome is None
    assert runtime.get_node(node.id).status == NodeStatus.AGENT_UNAVAILABLE
    events = runtime.events.query(run.id).events
    assert any(event.type == "provider_blocked" for event in events)
    dispatch_dirs = list((tmp_path / ".squad" / "runs" / run.id / "dispatches").glob("*"))
    assert dispatch_dirs
    assert (dispatch_dirs[0] / "provider-health.json").exists()


def test_acceptance_report_creates_and_enforces_coverage_baseline(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("acceptance")
    node_types = {
        "squad-lead": "lead",
        "rapid-prototyper": "prototype",
        "software-architect": "architecture",
        "ui-designer": "design",
        "backend-architect": "backend",
        "frontend-developer": "frontend",
        "test-engineer": "test",
        "code-reviewer": "review",
        "reality-checker": "gate",
        "git-workflow-master": "release",
    }
    for agent_id in [agent.agent_id for agent in AgentRegistry.default().list_agents()]:
        node = runtime.create_node(run.id, agent_id, node_types[agent_id], agent_id, checkpoint_id="ckp-accept")
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
                workedAgainstCheckpoint="ckp-accept",
                agentContractVersion="v1",
            ),
            provider_used="claude_cli",
            provider_type="real_llm",
            provider_identity_verified=True,
        )
    GateEngine(runtime).evaluate_all(run.id)
    reporter = AcceptanceReporter(runtime)

    first = reporter.write_report(
        run.id,
        tmp_path / "acceptance.md",
        coverage_percent=90.0,
        codebase_memory={"status": "indexed", "project": "E-Project-squad-runtime-index-mirror", "nodes": 1, "edges": 1, "architecture": "ok"},
    )
    second = reporter.write_report(
        run.id,
        tmp_path / "acceptance-low.md",
        coverage_percent=80.0,
        codebase_memory={"status": "indexed", "project": "E-Project-squad-runtime-index-mirror", "nodes": 1, "edges": 1, "architecture": "ok"},
    )

    assert first["coverage_baseline_created"] is True
    assert (tmp_path / ".squad" / "acceptance" / "coverage-baseline.json").exists()
    assert first["conclusion"] == "FAIL"
    assert "coverage_baseline_created_requires_rerun" in first["risks"]
    assert second["conclusion"] == "FAIL"
    assert "coverage_below_baseline" in second["risks"]
