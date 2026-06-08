"""Tests for tool adapter path boundary security enforcement."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from squad_runtime.agent_registry import AgentRegistry
from squad_runtime.runtime import Runtime
from squad_runtime.state import NodeStatus
from squad_runtime.tool_adapter import ControlledToolAdapter
from squad_runtime.tool_permissions import ToolPermissionError


def _make_adapter(tmp_path: Path) -> tuple[ControlledToolAdapter, Runtime, str]:
    """Helper: create a runtime, run, node, and adapter for testing."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "safe.txt").write_text("safe content", encoding="utf-8")
    squad_dir = project / ".squad"
    runtime = Runtime.create(squad_dir)
    run = runtime.create_run("boundary test")
    node = runtime.create_node(run.id, "Test node", "backend", "backend-architect", checkpoint_id="ckp-1")
    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    registry = AgentRegistry.default()
    adapter = ControlledToolAdapter(runtime, project, registry)
    return adapter, runtime, node.id


def _event_types(runtime: Runtime, run_id: str) -> list[str]:
    return [e.type for e in runtime.events.query(run_id).events]


def _events_of_type(runtime: Runtime, run_id: str, event_type: str) -> list[dict]:
    return [e.payload for e in runtime.events.query(run_id).events if e.type == event_type]


# --- test_path_escape_denied ---


def test_path_escape_denied(tmp_path: Path):
    """Attempting to read_file with a path that escapes workspace should be denied."""
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    with pytest.raises(ToolPermissionError):
        adapter.call_tool(node_id, "read_file", {"path": "../../etc/passwd"})

    types = _event_types(runtime, run_id)
    assert "tool_permission_denied" in types
    denied = _events_of_type(runtime, run_id, "tool_permission_denied")[0]
    assert denied["failureClass"] == "SECURITY_VIOLATION"


# --- test_forbidden_root_denied ---


def test_forbidden_root_denied(tmp_path: Path):
    """Attempting to access .squad/squad.db should be denied."""
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    with pytest.raises(ToolPermissionError):
        adapter.call_tool(node_id, "read_file", {"path": ".squad/squad.db"})

    denied = _events_of_type(runtime, run_id, "tool_permission_denied")[0]
    assert denied["failureClass"] == "SECURITY_VIOLATION"
    assert "Forbidden path" in denied["reason"]


# --- test_symlink_escape_attempt_denied ---


@pytest.mark.skipif(sys.platform == "win32", reason="Symlinks require admin on Windows")
def test_symlink_escape_attempt_denied(tmp_path: Path):
    """A symlink escaping the workspace should be denied."""
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link = project / "escape.txt"
    link.symlink_to(outside)

    squad_dir = project / ".squad"
    runtime = Runtime.create(squad_dir)
    run = runtime.create_run("symlink test")
    node = runtime.create_node(run.id, "Test node", "backend", "backend-architect", checkpoint_id="ckp-1")
    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    registry = AgentRegistry.default()
    adapter = ControlledToolAdapter(runtime, project, registry)

    with pytest.raises(ToolPermissionError):
        adapter.call_tool(node.id, "read_file", {"path": "escape.txt"})


# --- test_command_not_declared_denied ---


def test_command_not_declared_denied(tmp_path: Path):
    """Trying to run_build with an unregistered command_id should be denied."""
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    with pytest.raises(ToolPermissionError, match="Unknown command id"):
        adapter.call_tool(node_id, "run_build", {"build_id": "nonexistent_build"})

    denied = _events_of_type(runtime, run_id, "tool_permission_denied")[0]
    assert denied["failureClass"] == "CONFIG_ERROR"
    assert denied["toolName"] == "run_build"


# --- test_forbidden_tool_type ---


def test_forbidden_tool_type(tmp_path: Path):
    """Trying to call 'shell' directly should be denied."""
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    with pytest.raises(ToolPermissionError, match="Forbidden tool"):
        adapter.call_tool(node_id, "shell", {"command": "ls"})

    denied = _events_of_type(runtime, run_id, "tool_permission_denied")[0]
    assert denied["failureClass"] == "SECURITY_VIOLATION"
    assert denied["toolName"] == "shell"


# --- test_forbidden_squad_events_ndjson ---


def test_forbidden_squad_events_ndjson(tmp_path: Path):
    """Accessing .squad/events.ndjson should be denied."""
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    with pytest.raises(ToolPermissionError):
        adapter.call_tool(node_id, "read_file", {"path": ".squad/events.ndjson"})

    denied = _events_of_type(runtime, run_id, "tool_permission_denied")[0]
    assert denied["failureClass"] == "SECURITY_VIOLATION"


# --- test_forbidden_squad_token ---


def test_forbidden_squad_token(tmp_path: Path):
    """Accessing .squad/token should be denied."""
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    with pytest.raises(ToolPermissionError):
        adapter.call_tool(node_id, "read_file", {"path": ".squad/token"})

    denied = _events_of_type(runtime, run_id, "tool_permission_denied")[0]
    assert denied["failureClass"] == "SECURITY_VIOLATION"


# --- test_unknown_tool_via_call_tool ---


def test_unknown_tool_via_call_tool(tmp_path: Path):
    """Calling a completely unknown tool name should be denied."""
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    with pytest.raises(ToolPermissionError, match="Unknown tool"):
        adapter.call_tool(node_id, "totally_fake_tool", {})

    denied = _events_of_type(runtime, run_id, "tool_permission_denied")[0]
    assert denied["failureClass"] == "CONFIG_ERROR"
