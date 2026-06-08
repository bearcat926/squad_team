"""Tests for tool session lifecycle and four-channel event invariants."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from squad_runtime.agent_contracts import AgentResult
from squad_runtime.agent_registry import AgentRegistry
from squad_runtime.runtime import Runtime
from squad_runtime.state import NodeStatus
from squad_runtime.tool_adapter import ControlledToolAdapter, ToolSession, ToolSessionConfig
from squad_runtime.tool_permissions import ToolPermissionError


def _make_adapter(tmp_path: Path) -> tuple[ControlledToolAdapter, Runtime, str]:
    """Helper: create a runtime, run, node, and adapter for testing."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "hello.txt").write_text("hello world", encoding="utf-8")
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("print('hi')", encoding="utf-8")
    (project / "README.md").write_text("# Project", encoding="utf-8")
    squad_dir = project / ".squad"
    runtime = Runtime.create(squad_dir)
    run = runtime.create_run("tool session test")
    node = runtime.create_node(run.id, "Test node", "backend", "backend-architect", checkpoint_id="ckp-1")
    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    registry = AgentRegistry.default()
    adapter = ControlledToolAdapter(runtime, project, registry)
    return adapter, runtime, node.id


def _make_adapter_for_agent(tmp_path: Path, agent_id: str) -> tuple[ControlledToolAdapter, Runtime, str]:
    """Helper: create adapter for a specific agent type."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "hello.txt").write_text("hello world", encoding="utf-8")
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("print('hi')", encoding="utf-8")
    (project / "README.md").write_text("# Project", encoding="utf-8")
    (project / "reports").mkdir()
    (project / "reports" / "summary.md").write_text("# Summary", encoding="utf-8")
    squad_dir = project / ".squad"
    runtime = Runtime.create(squad_dir)
    run = runtime.create_run(f"tool session test for {agent_id}")
    node = runtime.create_node(run.id, f"Test node for {agent_id}", "backend", agent_id, checkpoint_id="ckp-1")
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


# ====================================================================
# E2E Tests: full flow, max_rounds, timeout, illegal tool, four-channel
# ====================================================================


# --- test_e2e_tool_session_full_flow ---


def test_e2e_tool_session_full_flow(tmp_path: Path):
    """Start session -> read_file -> list_files -> register_artifact -> complete.
    Verify ALL events in order across three tool calls."""
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    session = adapter.start_tool_session(node_id, config=ToolSessionConfig(max_tool_rounds=5))

    # Round 1: read_file
    r1 = adapter.call_tool_in_session(session, "read_file", {"path": "hello.txt"})
    assert r1.content == "hello world"

    # Round 2: list_files
    r2 = adapter.call_tool_in_session(session, "list_files", {"glob": "**/*.txt"})
    assert "hello.txt" in r2.content

    # Round 3: register_artifact
    r3 = adapter.call_tool_in_session(session, "register_artifact", {
        "path": "hello.txt",
        "type": "text",
        "purpose": "test artifact",
    })
    assert r3.path == "hello.txt"

    # Complete session
    adapter.complete_tool_session(session)

    # Verify event sequence
    types = _event_types(runtime, run_id)
    # Expected order: session_started, [requested, allowed, completed] x3, session_completed
    assert types.index("tool_session_started") < types.index("tool_call_requested")

    # Three requested/allowed/completed triplets
    assert len(_events_of_type(runtime, run_id, "tool_call_requested")) == 3
    assert len(_events_of_type(runtime, run_id, "tool_call_allowed")) == 3
    assert len(_events_of_type(runtime, run_id, "tool_call_completed")) == 3

    # Verify round numbers
    completions = _events_of_type(runtime, run_id, "tool_call_completed")
    assert completions[0]["round"] == 1
    assert completions[1]["round"] == 2
    assert completions[2]["round"] == 3

    # Session completed with success
    completed = _events_of_type(runtime, run_id, "tool_session_completed")[0]
    assert completed["status"] == "success"
    assert completed["roundCount"] == 3
    assert len(completed["calls"]) == 3
    assert session.status == "success"
    assert session.round_count == 3


# --- test_e2e_tool_session_max_rounds_enforcement ---


def test_e2e_tool_session_max_rounds_enforcement(tmp_path: Path):
    """max_rounds=2, make 3 calls, verify 3rd raises and session completes with max_rounds_exceeded."""
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    config = ToolSessionConfig(max_tool_rounds=2)
    session = adapter.start_tool_session(node_id, config=config)

    # Call 1 succeeds
    adapter.call_tool_in_session(session, "read_file", {"path": "hello.txt"})
    assert session.round_count == 1

    # Call 2 succeeds
    adapter.call_tool_in_session(session, "read_file", {"path": "hello.txt"})
    assert session.round_count == 2

    # Call 3 exceeds max_rounds
    with pytest.raises(ToolPermissionError, match="max rounds"):
        adapter.call_tool_in_session(session, "list_files", {})

    # Session auto-completed with max_rounds_exceeded
    assert session.status == "max_rounds_exceeded"
    completed = _events_of_type(runtime, run_id, "tool_session_completed")[0]
    assert completed["status"] == "max_rounds_exceeded"
    assert "2 rounds" in completed["detail"]

    # Only 2 successful completions recorded
    success_completions = [
        c for c in _events_of_type(runtime, run_id, "tool_call_completed")
        if c["status"] == "success"
    ]
    assert len(success_completions) == 2


# --- test_e2e_tool_session_timeout_enforcement ---


def test_e2e_tool_session_timeout_enforcement(tmp_path: Path):
    """session_timeout_seconds=0, verify timeout triggers on first call."""
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    config = ToolSessionConfig(session_timeout_seconds=0)
    session = adapter.start_tool_session(node_id, config=config)

    # Any call should time out immediately (0-second window)
    with pytest.raises(ToolPermissionError, match="timed out"):
        adapter.call_tool_in_session(session, "read_file", {"path": "hello.txt"})

    assert session.status == "timeout"
    completed = _events_of_type(runtime, run_id, "tool_session_completed")[0]
    assert completed["status"] == "timeout"
    assert completed["reason"] == "session_timeout"
    assert completed["roundCount"] == 0

    # No successful tool calls
    success_completions = [
        c for c in _events_of_type(runtime, run_id, "tool_call_completed")
        if c["status"] == "success"
    ]
    assert len(success_completions) == 0


# --- test_e2e_tool_session_illegal_tool_denial ---


def test_e2e_tool_session_illegal_tool_denial(tmp_path: Path):
    """Request 'shell' in session, verify denied event + session completed as denied."""
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    session = adapter.start_tool_session(node_id)

    with pytest.raises(ToolPermissionError, match="Illegal tool"):
        adapter.call_tool_in_session(session, "shell", {"command": "rm -rf /"})

    # Full event chain for the denied call
    types = _event_types(runtime, run_id)
    assert "tool_session_started" in types
    assert "tool_call_requested" in types
    assert "tool_call_denied" in types
    assert "tool_session_completed" in types
    # No allowed or completed-success events
    assert "tool_call_allowed" not in types

    denied = _events_of_type(runtime, run_id, "tool_call_denied")[0]
    assert denied["toolName"] == "shell"
    assert denied["reason"] == "illegal_tool"
    assert denied["denialCode"] == "illegal_tool"

    completed = _events_of_type(runtime, run_id, "tool_session_completed")[0]
    assert completed["status"] == "denied"
    assert completed["reason"] == "illegal_tool"

    # Session state
    assert session.status == "denied"
    assert session.round_count == 0


# --- test_e2e_four_channel_events_success ---


def test_e2e_four_channel_events_success(tmp_path: Path):
    """Successful call -> verify tool events + session outcome + no blocking risks."""
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    session = adapter.start_tool_session(node_id)
    result = adapter.call_tool_in_session(session, "read_file", {"path": "hello.txt"})
    adapter.complete_tool_session(session)

    # Channel 1: events
    types = _event_types(runtime, run_id)
    for expected in ("tool_session_started", "tool_call_requested", "tool_call_allowed", "tool_call_completed", "tool_session_completed"):
        assert expected in types, f"Missing event: {expected}"

    # Channel 2: tool result
    assert result.content == "hello world"
    assert result.path == "hello.txt"

    # Channel 3: session outcome
    assert session.status == "success"
    assert session.round_count == 1
    assert len(session.calls) == 1
    assert session.calls[0]["toolName"] == "read_file"
    assert session.calls[0]["status"] == "success"

    # Channel 4: no blocking risks (no denied events, no risk signals)
    assert "tool_call_denied" not in types
    completed = _events_of_type(runtime, run_id, "tool_session_completed")[0]
    assert completed["status"] == "success"
    assert completed["reason"] is None


# --- test_e2e_four_channel_events_denied ---


def test_e2e_four_channel_events_denied(tmp_path: Path):
    """Denied call -> verify tool events + session outcome=denied + risk signals."""
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    session = adapter.start_tool_session(node_id)

    with pytest.raises(ToolPermissionError):
        adapter.call_tool_in_session(session, "exec", {"code": "import os; os.system('ls')"})

    # Channel 1: events -- denied event present
    types = _event_types(runtime, run_id)
    assert "tool_call_requested" in types
    assert "tool_call_denied" in types
    assert "tool_session_completed" in types
    # No allowed event
    assert "tool_call_allowed" not in types

    # Channel 3: session state
    assert session.status == "denied"
    assert session.round_count == 0
    assert len(session.calls) == 0

    # Channel 4: risk signal
    completed = _events_of_type(runtime, run_id, "tool_session_completed")[0]
    assert completed["status"] == "denied"
    assert completed["reason"] == "illegal_tool"


# --- test_e2e_tool_session_with_real_commands ---


def test_e2e_tool_session_with_real_commands(tmp_path: Path):
    """Use run_test with a registered command, verify execution through session."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "hello.txt").write_text("hello world", encoding="utf-8")
    squad_dir = project / ".squad"
    runtime = Runtime.create(squad_dir)
    run = runtime.create_run("command test")
    node = runtime.create_node(run.id, "Test node", "backend", "backend-architect", checkpoint_id="ckp-1")
    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    registry = AgentRegistry.default()

    # Register a real command (echo)
    test_commands = {"echo_test": ["echo", "test passed"]}
    adapter = ControlledToolAdapter(runtime, project, registry, test_commands=test_commands)

    session = adapter.start_tool_session(node.id)
    run_id = run.id

    # Round 1: run_test with registered command
    result = adapter.call_tool_in_session(session, "run_test", {"test_id": "echo_test"})
    assert result.exit_code == 0
    assert "test passed" in result.stdout

    # Round 2: read_file still works after run_test
    r2 = adapter.call_tool_in_session(session, "read_file", {"path": "hello.txt"})
    assert r2.content == "hello world"

    adapter.complete_tool_session(session)

    # Verify events
    completions = _events_of_type(runtime, run_id, "tool_call_completed")
    assert len(completions) == 2
    assert completions[0]["toolName"] == "run_test"
    assert completions[0]["status"] == "success"
    assert completions[1]["toolName"] == "read_file"
    assert completions[1]["status"] == "success"

    completed = _events_of_type(runtime, run_id, "tool_session_completed")[0]
    assert completed["status"] == "success"
    assert completed["roundCount"] == 2


# --- test_e2e_tool_session_preserves_backwards_compat ---


def test_e2e_tool_session_preserves_backwards_compat(tmp_path: Path):
    """Old call_tool() still works alongside new session API."""
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    # Use old API
    r1 = adapter.call_tool(node_id, "read_file", {"path": "hello.txt"})
    assert r1.content == "hello world"

    # Use new session API
    session = adapter.start_tool_session(node_id)
    r2 = adapter.call_tool_in_session(session, "read_file", {"path": "hello.txt"})
    assert r2.content == "hello world"
    adapter.complete_tool_session(session)

    # Old API: tool_call event, no session events from this call
    tool_call_events = [e for e in runtime.events.query(run_id).events if e.type == "tool_call"]
    assert len(tool_call_events) >= 1

    # New API: session events present
    assert "tool_session_started" in _event_types(runtime, run_id)
    assert "tool_session_completed" in _event_types(runtime, run_id)

    # Both can coexist in the same run
    assert session.status == "success"


# --- test_e2e_session_denied_then_new_session_succeeds ---


def test_e2e_session_denied_then_new_session_succeeds(tmp_path: Path):
    """A denied session does not block subsequent sessions."""
    adapter, runtime, node_id = _make_adapter(tmp_path)
    run_id = runtime.get_node(node_id).run_id

    # Session 1: denied
    s1 = adapter.start_tool_session(node_id)
    with pytest.raises(ToolPermissionError):
        adapter.call_tool_in_session(s1, "shell", {})
    assert s1.status == "denied"

    # Session 2: succeeds
    s2 = adapter.start_tool_session(node_id)
    result = adapter.call_tool_in_session(s2, "read_file", {"path": "hello.txt"})
    adapter.complete_tool_session(s2)
    assert result.content == "hello world"
    assert s2.status == "success"

    # Two session_completed events
    completions = _events_of_type(runtime, run_id, "tool_session_completed")
    assert len(completions) == 2
    assert completions[0]["status"] == "denied"
    assert completions[1]["status"] == "success"
