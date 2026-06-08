"""Tests for tool session lifecycle and four-channel event invariants."""

from __future__ import annotations

from pathlib import Path

import pytest

from squad_runtime.agent_registry import AgentRegistry
from squad_runtime.runtime import Runtime
from squad_runtime.state import NodeStatus
from squad_runtime.tool_adapter import ControlledToolAdapter, ToolSessionConfig
from squad_runtime.tool_permissions import ToolPermissionError


def _make_adapter(tmp_path: Path) -> tuple[ControlledToolAdapter, Runtime, str]:
    """Helper: create a runtime, run, node, and adapter for testing."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "hello.txt").write_text("hello world", encoding="utf-8")
    squad_dir = project / ".squad"
    runtime = Runtime.create(squad_dir)
    run = runtime.create_run("tool session test")
    node = runtime.create_node(run.id, "Test node", "backend", "backend-architect", checkpoint_id="ckp-1")
    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    registry = AgentRegistry.default()
    adapter = ControlledToolAdapter(runtime, project, registry)
    return adapter, runtime, node.id


def _event_types(runtime: Runtime, run_id: str) -> list[str]:
    return [e.type for e in runtime.events.query(run_id).events]


def _events_of_type(runtime: Runtime, run_id: str, event_type: str) -> list[dict]:
    return [e.payload for e in runtime.events.query(run_id).events if e.type == event_type]


# --- test_tool_session_started_and_completed_events ---


def test_tool_session_started_and_completed_events(tmp_path: Path):
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    session = adapter.start_tool_session(node_id)
    adapter.call_tool_in_session(session, "read_file", {"path": "hello.txt"})
    adapter.complete_tool_session(session)

    types = _event_types(runtime, run_id)
    assert "tool_session_started" in types
    assert "tool_session_completed" in types

    started = _events_of_type(runtime, run_id, "tool_session_started")[0]
    assert started["sessionId"] == session.session_id
    assert started["nodeId"] == node_id

    completed = _events_of_type(runtime, run_id, "tool_session_completed")[0]
    assert completed["status"] == "success"
    assert completed["roundCount"] == 1
    assert completed["elapsedMs"] >= 0


# --- test_tool_session_max_rounds_exceeded ---


def test_tool_session_max_rounds_exceeded(tmp_path: Path):
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    config = ToolSessionConfig(max_tool_rounds=1)
    session = adapter.start_tool_session(node_id, config=config)

    # First call succeeds
    adapter.call_tool_in_session(session, "read_file", {"path": "hello.txt"})

    # Second call exceeds max rounds
    with pytest.raises(ToolPermissionError, match="max rounds"):
        adapter.call_tool_in_session(session, "read_file", {"path": "hello.txt"})

    completed = _events_of_type(runtime, run_id, "tool_session_completed")[0]
    assert completed["status"] == "max_rounds_exceeded"
    assert completed["detail"] is not None


# --- test_tool_session_timeout ---


def test_tool_session_timeout(tmp_path: Path):
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    config = ToolSessionConfig(session_timeout_seconds=0)
    session = adapter.start_tool_session(node_id, config=config)

    with pytest.raises(ToolPermissionError, match="timed out"):
        adapter.call_tool_in_session(session, "read_file", {"path": "hello.txt"})

    completed = _events_of_type(runtime, run_id, "tool_session_completed")[0]
    assert completed["status"] == "timeout"
    assert completed["reason"] == "session_timeout"


# --- test_tool_call_requested_allowed_completed_sequence ---


def test_tool_call_requested_allowed_completed_sequence(tmp_path: Path):
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    session = adapter.start_tool_session(node_id)
    adapter.call_tool_in_session(session, "read_file", {"path": "hello.txt"})

    types = _event_types(runtime, run_id)
    # Find the three session-scoped event types in order
    requested_idx = types.index("tool_call_requested")
    allowed_idx = types.index("tool_call_allowed")
    completed_idx = types.index("tool_call_completed")

    assert requested_idx < allowed_idx < completed_idx

    requested = _events_of_type(runtime, run_id, "tool_call_requested")[0]
    assert requested["toolName"] == "read_file"
    assert requested["round"] == 1

    allowed = _events_of_type(runtime, run_id, "tool_call_allowed")[0]
    assert allowed["toolName"] == "read_file"

    completed = _events_of_type(runtime, run_id, "tool_call_completed")[0]
    assert completed["status"] == "success"
    assert completed["round"] == 1


# --- test_illegal_tool_emits_denied_event ---


def test_illegal_tool_emits_denied_event(tmp_path: Path):
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    session = adapter.start_tool_session(node_id)

    with pytest.raises(ToolPermissionError, match="Illegal tool"):
        adapter.call_tool_in_session(session, "shell", {})

    types = _event_types(runtime, run_id)
    assert "tool_call_requested" in types
    assert "tool_call_denied" in types
    assert "tool_session_completed" in types

    denied = _events_of_type(runtime, run_id, "tool_call_denied")[0]
    assert denied["toolName"] == "shell"
    assert denied["reason"] == "illegal_tool"
    assert denied["denialCode"] == "illegal_tool"

    completed = _events_of_type(runtime, run_id, "tool_session_completed")[0]
    assert completed["status"] == "denied"
    assert completed["reason"] == "illegal_tool"


# --- test_unknown_tool_emits_denied_event ---


def test_unknown_tool_emits_denied_event(tmp_path: Path):
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    session = adapter.start_tool_session(node_id)

    with pytest.raises(ToolPermissionError):
        adapter.call_tool_in_session(session, "nonexistent_tool", {})

    denied = _events_of_type(runtime, run_id, "tool_call_denied")[0]
    assert denied["toolName"] == "nonexistent_tool"
    assert denied["reason"] == "unknown_tool"

    completed = _events_of_type(runtime, run_id, "tool_session_completed")[0]
    assert completed["status"] == "denied"


# --- test_four_channel_invariants_success ---


def test_four_channel_invariants_success(tmp_path: Path):
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    session = adapter.start_tool_session(node_id)
    result = adapter.call_tool_in_session(session, "read_file", {"path": "hello.txt"})
    adapter.complete_tool_session(session)

    # Channel 1: events -- all session lifecycle events present
    types = _event_types(runtime, run_id)
    for expected in ("tool_session_started", "tool_call_requested", "tool_call_allowed", "tool_call_completed", "tool_session_completed"):
        assert expected in types, f"Missing event: {expected}"

    # Channel 2: tool result -- actual ToolResult returned
    assert result.content == "hello world"

    # Channel 3: session state
    assert session.status == "success"
    assert session.round_count == 1
    assert len(session.calls) == 1
    assert session.calls[0]["status"] == "success"

    # Channel 4: no blocking risks on success
    completed = _events_of_type(runtime, run_id, "tool_session_completed")[0]
    assert completed["status"] == "success"
    assert completed["reason"] is None


# --- test_four_channel_invariants_denied ---


def test_four_channel_invariants_denied(tmp_path: Path):
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    session = adapter.start_tool_session(node_id)

    with pytest.raises(ToolPermissionError):
        adapter.call_tool_in_session(session, "shell", {})

    # Channel 1: events -- denied event present
    types = _event_types(runtime, run_id)
    assert "tool_call_denied" in types
    assert "tool_session_completed" in types

    # Channel 3: session state -- marked as denied, round not incremented (denied before execution)
    assert session.status == "denied"
    assert session.round_count == 0
    assert len(session.calls) == 0

    # Channel 4: risk signal present
    completed = _events_of_type(runtime, run_id, "tool_session_completed")[0]
    assert completed["status"] == "denied"
    assert completed["reason"] == "illegal_tool"


# --- test_tool_session_config_defaults ---


def test_tool_session_config_defaults():
    config = ToolSessionConfig()
    assert config.max_tool_rounds == 5
    assert config.tool_call_timeout_seconds == 30
    assert config.session_timeout_seconds == 180


# --- test_tool_session_custom_config ---


def test_tool_session_custom_config(tmp_path: Path):
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    config = ToolSessionConfig(max_tool_rounds=10, session_timeout_seconds=600)
    session = adapter.start_tool_session(node_id, config=config)

    assert session.config.max_tool_rounds == 10
    assert session.config.session_timeout_seconds == 600

    started = _events_of_type(runtime, run_id, "tool_session_started")[0]
    assert started["maxToolRounds"] == 10
    assert started["sessionTimeoutSeconds"] == 600


# --- test_backwards_compatible_call_tool ---


def test_backwards_compatible_call_tool(tmp_path: Path):
    """The old call_tool() method still works without a session."""
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    result = adapter.call_tool(node_id, "read_file", {"path": "hello.txt"})

    assert result.content == "hello world"
    # Per-tool-call event still recorded
    assert "tool_call" in _event_types(runtime, run_id)
    # No session events
    assert "tool_session_started" not in _event_types(runtime, run_id)
    assert "tool_session_completed" not in _event_types(runtime, run_id)


# --- test_session_idempotent_completion ---


def test_session_idempotent_completion(tmp_path: Path):
    """Completing a session twice should only emit one tool_session_completed event."""
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    session = adapter.start_tool_session(node_id)
    adapter.complete_tool_session(session)
    adapter.complete_tool_session(session)  # Second call is a no-op

    completions = _events_of_type(runtime, run_id, "tool_session_completed")
    assert len(completions) == 1


# --- test_content_redacted_in_requested_args ---


def test_content_redacted_in_requested_args(tmp_path: Path):
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    session = adapter.start_tool_session(node_id)
    # This will fail (write_file needs base_snapshot_id), but requested should still be emitted
    with pytest.raises(ToolPermissionError):
        adapter.call_tool_in_session(session, "write_file", {"path": "out.txt", "content": "secret", "base_snapshot_id": "x"})

    requested = _events_of_type(runtime, run_id, "tool_call_requested")[0]
    assert "content" not in requested.get("args", {})
