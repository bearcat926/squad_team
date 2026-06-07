from __future__ import annotations

from pathlib import Path

import pytest

from squad_runtime.agent_registry import AgentRegistry
from squad_runtime.runtime import Runtime
from squad_runtime.tool_adapter import ControlledToolAdapter
from squad_runtime.tool_permissions import ToolPermissionError


def test_tool_adapter_allows_read_and_records_schema_versioned_event(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.js").write_text("console.log('ok')\n", encoding="utf-8")
    runtime = Runtime.create(project / ".squad")
    run = runtime.create_run("tools")
    node = runtime.create_node(run.id, "Read", "frontend", "frontend-developer")

    adapter = ControlledToolAdapter(runtime, project, AgentRegistry.default())
    result = adapter.read_file(node.id, "app.js")

    assert result.content == "console.log('ok')\n"
    tool_events = [event for event in runtime.events.query(run.id).events if event.type == "tool_call"]
    assert tool_events[-1].payload["schemaVersion"] == "tool-call/v1"
    assert tool_events[-1].payload["toolName"] == "read_file"
    assert tool_events[-1].payload["deterministicReplay"] is True
    assert tool_events[-1].payload["replayMode"] == "deterministic"
    assert tool_events[-1].payload["dependencyLocking"] == "none"
    assert tool_events[-1].payload["eventHash"].startswith("sha256:")


def test_tool_adapter_denies_forbidden_squad_token_read(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    runtime = Runtime.create(project / ".squad")
    (project / ".squad" / "token").write_text("secret", encoding="utf-8")
    run = runtime.create_run("tools")
    node = runtime.create_node(run.id, "Read token", "frontend", "frontend-developer")
    adapter = ControlledToolAdapter(runtime, project, AgentRegistry.default())

    with pytest.raises(ToolPermissionError) as error:
        adapter.read_file(node.id, ".squad/token")

    assert error.value.failure_class == "SECURITY_VIOLATION"
    event = runtime.events.query(run.id).events[-1]
    assert event.type == "tool_permission_denied"
    assert event.payload["failureClass"] == "SECURITY_VIOLATION"


def test_tool_adapter_write_binds_snapshot_and_generates_result_snapshot(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    runtime = Runtime.create(project / ".squad")
    run = runtime.create_run("tools")
    node = runtime.create_node(run.id, "Write", "frontend", "frontend-developer", checkpoint_id="snap-base")
    adapter = ControlledToolAdapter(runtime, project, AgentRegistry.default())

    result = adapter.write_file(node.id, "app.js", "console.log('new')\n", base_snapshot_id="snap-base")

    assert (project / "app.js").read_text(encoding="utf-8") == "console.log('new')\n"
    assert result.base_snapshot_id == "snap-base"
    assert result.result_snapshot_id is not None
    assert result.result_snapshot_id.startswith("snap-")


def test_tool_adapter_denies_reviewer_source_patch_and_unknown_test(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("print('old')\n", encoding="utf-8")
    runtime = Runtime.create(project / ".squad")
    run = runtime.create_run("tools")
    reviewer = runtime.create_node(run.id, "Review", "review", "code-reviewer")
    tester = runtime.create_node(run.id, "Test", "test", "test-engineer")
    adapter = ControlledToolAdapter(runtime, project, AgentRegistry.default(), test_commands={"unit": ["python", "-c", "print('ok')"]})

    with pytest.raises(ToolPermissionError) as patch_error:
        adapter.apply_patch(reviewer.id, "app.py", "old", "new", base_snapshot_id=reviewer.checkpoint_id)
    assert patch_error.value.failure_class == "POLICY_VIOLATION"

    with pytest.raises(ToolPermissionError) as test_error:
        adapter.run_test(tester.id, "missing")
    assert test_error.value.failure_class == "CONFIG_ERROR"


def test_tool_adapter_denies_unknown_run_command_and_direct_seal_snapshot(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    runtime = Runtime.create(project / ".squad")
    run = runtime.create_run("tools")
    node = runtime.create_node(run.id, "Unknown", "frontend", "frontend-developer")
    adapter = ControlledToolAdapter(runtime, project, AgentRegistry.default())

    with pytest.raises(ToolPermissionError) as command_error:
        adapter.call_tool(node.id, "run_command", {"command": "dir"})
    assert command_error.value.failure_class == "SECURITY_VIOLATION"

    with pytest.raises(ToolPermissionError) as seal_error:
        adapter.call_tool(node.id, "seal_snapshot", {})
    assert seal_error.value.failure_class == "POLICY_VIOLATION"
