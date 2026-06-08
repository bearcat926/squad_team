"""Tests for AcceptanceReporter risk detection of tool-loop and provider events."""

from __future__ import annotations

from pathlib import Path

from squad_runtime.acceptance import AcceptanceReporter
from squad_runtime.agent_contracts import AgentResult
from squad_runtime.runtime import Runtime
from squad_runtime.state import NodeStatus


def _setup_run(runtime: Runtime, agent_id: str = "squad-lead") -> str:
    run = runtime.create_run("risk event test")
    node = runtime.create_node(run.id, "Lead", "lead", agent_id, checkpoint_id="ckp-1")
    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    runtime.transition_node(node.id, NodeStatus.READY, NodeStatus.RUNNING, "running")
    runtime.transition_node(node.id, NodeStatus.RUNNING, NodeStatus.PASS, "pass")
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
            confidence=0.9,
            workedAgainstCheckpoint="ckp-1",
            agentContractVersion="v1",
        ),
        provider_used="claude_cli",
        provider_type="real_llm",
        provider_identity_verified=True,
    )
    for gate_name in ["test_gate", "code_review_gate", "reality_checker_gate", "release_gate"]:
        runtime.upsert_gate_state(run.id, gate_name, "pass", "ok")
    return run.id


def test_provider_rate_limited_event_adds_risk(tmp_path: Path) -> None:
    runtime = Runtime.create(tmp_path / ".squad")
    run_id = _setup_run(runtime)
    runtime.events.append(run_id, "provider_rate_limited", {"agentId": "squad-lead"})

    payload = AcceptanceReporter(runtime).write_report(
        run_id,
        tmp_path / "report.md",
        coverage_percent=99.0,
        codebase_memory={"status": "indexed", "architecture": {"packages": []}},
        required_agent_ids=["squad-lead"],
    )

    assert "provider_rate_limited" in payload["risks"]


def test_tool_loop_timeout_adds_risk(tmp_path: Path) -> None:
    runtime = Runtime.create(tmp_path / ".squad")
    run_id = _setup_run(runtime)
    runtime.events.append(run_id, "tool_loop_timeout", {"agentId": "squad-lead"})

    payload = AcceptanceReporter(runtime).write_report(
        run_id,
        tmp_path / "report.md",
        coverage_percent=99.0,
        codebase_memory={"status": "indexed", "architecture": {"packages": []}},
        required_agent_ids=["squad-lead"],
    )

    assert "tool_loop_timeout" in payload["risks"]


def test_tool_loop_max_rounds_exceeded_adds_risk(tmp_path: Path) -> None:
    runtime = Runtime.create(tmp_path / ".squad")
    run_id = _setup_run(runtime)
    runtime.events.append(run_id, "tool_loop_max_rounds_exceeded", {"agentId": "squad-lead"})

    payload = AcceptanceReporter(runtime).write_report(
        run_id,
        tmp_path / "report.md",
        coverage_percent=99.0,
        codebase_memory={"status": "indexed", "architecture": {"packages": []}},
        required_agent_ids=["squad-lead"],
    )

    assert "tool_loop_max_rounds_exceeded" in payload["risks"]


def test_illegal_tool_requested_adds_risk(tmp_path: Path) -> None:
    runtime = Runtime.create(tmp_path / ".squad")
    run_id = _setup_run(runtime)
    runtime.events.append(run_id, "illegal_tool_requested", {"agentId": "squad-lead"})

    payload = AcceptanceReporter(runtime).write_report(
        run_id,
        tmp_path / "report.md",
        coverage_percent=99.0,
        codebase_memory={"status": "indexed", "architecture": {"packages": []}},
        required_agent_ids=["squad-lead"],
    )

    assert "illegal_tool_requested" in payload["risks"]


def test_silent_provider_fallback_adds_risk(tmp_path: Path) -> None:
    runtime = Runtime.create(tmp_path / ".squad")
    run_id = _setup_run(runtime)
    runtime.events.append(run_id, "silent_provider_fallback", {"agentId": "squad-lead"})

    payload = AcceptanceReporter(runtime).write_report(
        run_id,
        tmp_path / "report.md",
        coverage_percent=99.0,
        codebase_memory={"status": "indexed", "architecture": {"packages": []}},
        required_agent_ids=["squad-lead"],
    )

    assert "silent_provider_fallback" in payload["risks"]


def test_provider_error_adds_risk(tmp_path: Path) -> None:
    runtime = Runtime.create(tmp_path / ".squad")
    run_id = _setup_run(runtime)
    runtime.events.append(run_id, "provider_error", {"agentId": "squad-lead"})

    payload = AcceptanceReporter(runtime).write_report(
        run_id,
        tmp_path / "report.md",
        coverage_percent=99.0,
        codebase_memory={"status": "indexed", "architecture": {"packages": []}},
        required_agent_ids=["squad-lead"],
    )

    assert "provider_error" in payload["risks"]


def test_existing_risks_still_work(tmp_path: Path) -> None:
    runtime = Runtime.create(tmp_path / ".squad")
    run_id = _setup_run(runtime)
    runtime.events.append(run_id, "provider_blocked", {"agentId": "squad-lead"})
    runtime.events.append(run_id, "agent_timeout", {"agentId": "squad-lead"})
    runtime.events.append(run_id, "checkpoint_mismatch", {"agentId": "squad-lead"})

    payload = AcceptanceReporter(runtime).write_report(
        run_id,
        tmp_path / "report.md",
        coverage_percent=99.0,
        codebase_memory={"status": "indexed", "architecture": {"packages": []}},
        required_agent_ids=["squad-lead"],
    )

    assert "provider_blocked" in payload["risks"]
    assert "agent_timeout" in payload["risks"]
    assert "checkpoint_mismatch" in payload["risks"]


def test_no_duplicate_risks(tmp_path: Path) -> None:
    runtime = Runtime.create(tmp_path / ".squad")
    run_id = _setup_run(runtime)
    runtime.events.append(run_id, "tool_loop_timeout", {"agentId": "squad-lead"})
    runtime.events.append(run_id, "tool_loop_timeout", {"agentId": "squad-lead"})
    runtime.events.append(run_id, "tool_loop_timeout", {"agentId": "squad-lead"})

    payload = AcceptanceReporter(runtime).write_report(
        run_id,
        tmp_path / "report.md",
        coverage_percent=99.0,
        codebase_memory={"status": "indexed", "architecture": {"packages": []}},
        required_agent_ids=["squad-lead"],
    )

    assert payload["risks"].count("tool_loop_timeout") == 1
