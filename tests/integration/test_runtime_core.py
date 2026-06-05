import asyncio
import json
from pathlib import Path

import pytest

from squad_runtime.agent_contracts import AgentResult, validate_agent_result
from squad_runtime.event_store import EventStore
from squad_runtime.gate_engine import GateEngine
from squad_runtime.mock_agents import MockAgentFactory
from squad_runtime.runtime import Runtime
from squad_runtime.state import InvalidTransition, NodeStatus


def test_event_store_assigns_sequence_and_cursor(tmp_path: Path):
    event_store = EventStore(tmp_path / ".squad")
    first = event_store.append("run-1", "run_created", {"goal": "build"}, critical=True)
    second = event_store.append("run-1", "node_status_changed", {"nodeId": "n1"}, critical=True)

    assert first.sequence_number == 1
    assert second.sequence_number == 2

    page = event_store.query("run-1", cursor=1, limit=10)
    assert [event.type for event in page.events] == ["node_status_changed"]
    assert page.next_cursor is None

    ndjson_lines = (tmp_path / ".squad" / "events.ndjson").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["sequenceNumber"] for line in ndjson_lines] == [1, 2]
    event_store.close()


def test_event_store_rebuilds_ndjson_once_when_mirror_drifts(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    event_store = EventStore(squad_dir)
    event_store.append("run-1", "run_created", {"goal": "build"}, critical=True)
    (squad_dir / "events.ndjson").write_text("", encoding="utf-8")
    event_store.close()

    recovered_store = EventStore(squad_dir)

    system_events = recovered_store.query("system").events
    assert [event.type for event in system_events] == ["event_store_consistency_warning"]
    assert system_events[0].payload["sqliteEventCount"] == 1
    assert system_events[0].payload["ndjsonLineCount"] == 0
    sqlite_event_count = len(recovered_store.query("run-1").events) + len(system_events)
    ndjson_line_count = len((squad_dir / "events.ndjson").read_text(encoding="utf-8").splitlines())
    assert ndjson_line_count == sqlite_event_count
    recovered_store.close()

    reopened_store = EventStore(squad_dir)

    assert [event.type for event in reopened_store.query("system").events] == ["event_store_consistency_warning"]
    reopened_store.close()


def test_state_manager_enforces_terminal_stale_and_blocked_reason(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("ship a test project")
    node = runtime.create_node(run.id, "Backend task", "backend", "backend-architect")

    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    runtime.transition_node(node.id, NodeStatus.READY, NodeStatus.RUNNING, "dispatch")
    runtime.transition_node(node.id, NodeStatus.RUNNING, NodeStatus.PASS, "agent_result")
    runtime.transition_node(node.id, NodeStatus.PASS, NodeStatus.STALE, "directive_changed")

    with pytest.raises(InvalidTransition):
        runtime.transition_node(node.id, NodeStatus.STALE, NodeStatus.DONE, "should_not_finish_stale")

    blocked = runtime.create_node(run.id, "Review task", "review", "code-reviewer")
    with pytest.raises(ValueError):
        runtime.transition_node(blocked.id, NodeStatus.TODO, NodeStatus.BLOCKED, "missing reason")
    runtime.transition_node(
        blocked.id,
        NodeStatus.TODO,
        NodeStatus.BLOCKED,
        "missing test",
        blocked_reason_code="missing_test_pass",
    )
    assert runtime.get_node(blocked.id).blocked_reason_code == "missing_test_pass"
    runtime.close()


def test_late_agent_result_after_cancel_becomes_stale_advisory(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("race condition")
    node = runtime.create_node(run.id, "Frontend task", "frontend", "frontend-developer")

    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    runtime.transition_node(node.id, NodeStatus.READY, NodeStatus.RUNNING, "dispatch")
    runtime.transition_node(node.id, NodeStatus.RUNNING, NodeStatus.CANCELED, "user cancel")

    result = AgentResult(
        taskNodeId=node.id,
        agentId="frontend-developer",
        status="pass",
        summary="late success",
        evidence=[],
        artifacts=[],
        risks=[],
        nextActions=[],
        confidence=0.9,
        workedAgainstCheckpoint="ckp-1",
        agentContractVersion="v1",
    )
    outcome = runtime.apply_agent_result(result)

    assert outcome == "stale_advisory"
    assert runtime.get_node(node.id).status == NodeStatus.CANCELED
    assert runtime.events.query(run.id).events[-1].type == "stale_advisory"
    runtime.close()


def test_agent_result_validation_rejects_path_traversal(tmp_path: Path):
    result = AgentResult(
        taskNodeId="node-1",
        agentId="backend-architect",
        status="pass",
        summary="wrote files",
        evidence=[],
        artifacts=[{"name": "escape", "path": "../outside.txt"}],
        risks=[],
        nextActions=[],
        confidence=0.5,
        workedAgainstCheckpoint="ckp-1",
        agentContractVersion="v1",
    )

    validation = validate_agent_result(result, tmp_path / ".squad" / "artifacts", "ckp-1")
    assert not validation.valid
    assert "artifact_path_invalid" in validation.errors


def test_gate_engine_filters_inactive_tests_and_blocks_release(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("gate run")

    active_test = runtime.create_node(run.id, "Current test", "test", "test-engineer")
    stale_test = runtime.create_node(run.id, "Old test", "test", "test-engineer")
    review = runtime.create_node(run.id, "Code review", "review", "code-reviewer")
    reality = runtime.create_node(run.id, "Reality check", "gate", "reality-checker")

    runtime.transition_node(active_test.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    runtime.transition_node(active_test.id, NodeStatus.READY, NodeStatus.RUNNING, "dispatch")
    runtime.transition_node(active_test.id, NodeStatus.RUNNING, NodeStatus.PASS, "test passed")
    runtime.transition_node(stale_test.id, NodeStatus.TODO, NodeStatus.STALE, "replaced")
    runtime.transition_node(review.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    runtime.transition_node(review.id, NodeStatus.READY, NodeStatus.RUNNING, "dispatch")
    runtime.transition_node(review.id, NodeStatus.RUNNING, NodeStatus.PASS, "review approved")
    runtime.transition_node(reality.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    runtime.transition_node(reality.id, NodeStatus.READY, NodeStatus.RUNNING, "dispatch")
    runtime.transition_node(reality.id, NodeStatus.RUNNING, NodeStatus.PASS, "readiness pass")

    gates = GateEngine(runtime).evaluate_all(run.id)
    assert gates["test_gate"].status == "pass"
    assert gates["code_review_gate"].status == "pass"
    assert gates["reality_checker_gate"].status == "pass"
    assert gates["release_gate"].status == "pass"

    failing_runtime = Runtime.create(tmp_path / "blocked" / ".squad")
    blocked_run = failing_runtime.create_run("blocked gate run")
    test_node = failing_runtime.create_node(blocked_run.id, "Test", "test", "test-engineer")
    review_node = failing_runtime.create_node(blocked_run.id, "Review", "review", "code-reviewer")
    failing_runtime.transition_node(test_node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    failing_runtime.transition_node(test_node.id, NodeStatus.READY, NodeStatus.RUNNING, "dispatch")
    failing_runtime.transition_node(test_node.id, NodeStatus.RUNNING, NodeStatus.PASS, "test passed")
    failing_runtime.transition_node(review_node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    failing_runtime.transition_node(review_node.id, NodeStatus.READY, NodeStatus.RUNNING, "dispatch")
    failing_runtime.transition_node(review_node.id, NodeStatus.RUNNING, NodeStatus.FAIL, "P1 finding")

    blocked_gates = GateEngine(failing_runtime).evaluate_all(blocked_run.id)
    assert blocked_gates["code_review_gate"].status == "fail"
    assert blocked_gates["release_gate"].status == "blocked"
    assert blocked_gates["release_gate"].blocked_reason_code == "missing_review_pass"
    runtime.close()
    failing_runtime.close()


def test_mock_agent_emits_progress_and_structured_result():
    agent = MockAgentFactory.create(
        "backend",
        {
            "agent_id": "backend-architect",
            "step_delay_sec": 0,
            "failure_mode": "success",
        },
    )
    heartbeats = []
    progress = []

    async def run_agent():
        return await agent.execute(
            {"taskNodeId": "node-1", "dispatchId": "dispatch-1", "checkpoint": "ckp-1"},
            {
                "on_heartbeat": lambda payload: heartbeats.append(payload),
                "on_progress": lambda payload: progress.append(payload),
            },
        )

    result = asyncio.run(run_agent())

    assert heartbeats
    assert progress
    assert result["status"] == "pass"
    assert result["workedAgainstCheckpoint"] == "ckp-1"
