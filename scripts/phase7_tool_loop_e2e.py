#!/usr/bin/env python3
"""Phase 7: E2E tool loop integration test with tool_session.

Creates a temporary .squad directory, sets up a full Runtime with all 10 agents,
starts a tool session per agent, performs tool calls, records events, verifies
four-channel invariants, and outputs a JSON report.

Usage:
    python scripts/phase7_tool_loop_e2e.py --output <path>
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

# Ensure the project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from squad_runtime.agent_registry import AgentRegistry
from squad_runtime.runtime import Runtime
from squad_runtime.state import NodeStatus
from squad_runtime.tool_adapter import ControlledToolAdapter, ToolSessionConfig
from squad_runtime.tool_permissions import ToolPermissionError


def _all_events(runtime: Runtime, run_id: str) -> list:
    """Fetch all events for a run, handling pagination."""
    all_events = []
    cursor = None
    while True:
        page = runtime.events.query(run_id, cursor=cursor, limit=200)
        all_events.extend(page.events)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    return all_events


def _event_types_for(runtime: Runtime, run_id: str) -> list[str]:
    return [e.type for e in _all_events(runtime, run_id)]


def _events_of_type(runtime: Runtime, run_id: str, event_type: str) -> list[dict]:
    return [e.payload for e in _all_events(runtime, run_id) if e.type == event_type]
    """Check that ordered event types appear in the given sequence."""
    idx = -1
    for t in ordered:
        try:
            new_idx = types.index(t, idx + 1)
            idx = new_idx
        except ValueError:
            return False
    return True


def run_agent_session(
    adapter: ControlledToolAdapter,
    runtime: Runtime,
    node_id: str,
    agent_id: str,
    run_id: str,
) -> dict:
    """Run a full tool session for one agent. Returns detail dict."""
    config = ToolSessionConfig(max_tool_rounds=5, session_timeout_seconds=60)
    session = adapter.start_tool_session(node_id, config=config)

    calls_made = 0
    errors: list[str] = []

    # Call 1: read_file
    try:
        r = adapter.call_tool_in_session(session, "read_file", {"path": "hello.txt"})
        if r.content != "hello world":
            errors.append(f"read_file content mismatch: {r.content!r}")
        calls_made += 1
    except ToolPermissionError as e:
        errors.append(f"read_file denied: {e}")

    # Call 2: list_files
    try:
        r = adapter.call_tool_in_session(session, "list_files", {"glob": "**/*.txt"})
        calls_made += 1
    except ToolPermissionError as e:
        errors.append(f"list_files denied: {e}")

    # Call 3: register_artifact
    try:
        r = adapter.call_tool_in_session(session, "register_artifact", {
            "path": "hello.txt",
            "type": "text",
            "purpose": f"e2e test artifact for {agent_id}",
        })
        calls_made += 1
    except ToolPermissionError as e:
        errors.append(f"register_artifact denied: {e}")

    # Complete session
    adapter.complete_tool_session(session)

    # Verify four-channel invariants
    types = _event_types_for(runtime, run_id)
    four_channel_ok = True

    # Channel 1: events present
    required_events = [
        "tool_session_started",
        "tool_call_requested",
        "tool_call_allowed",
        "tool_call_completed",
        "tool_session_completed",
    ]
    for evt in required_events:
        if evt not in types:
            four_channel_ok = False
            errors.append(f"Missing event: {evt}")

    # Channel 2: session state
    if session.status != "success":
        four_channel_ok = False
        errors.append(f"Session status: {session.status}")

    # Channel 3: round count
    if session.round_count != calls_made:
        four_channel_ok = False
        errors.append(f"Round count mismatch: {session.round_count} != {calls_made}")

    # Channel 4: no denied events
    if "tool_call_denied" in types:
        four_channel_ok = False
        errors.append("Unexpected tool_call_denied event")

    completed_payload = _events_of_type(runtime, run_id, "tool_session_completed")
    if completed_payload and completed_payload[-1]["reason"] is not None:
        four_channel_ok = False
        errors.append(f"Session completed with reason: {completed_payload[-1]['reason']}")

    return {
        "agentId": agent_id,
        "sessionId": session.session_id,
        "status": session.status,
        "callsExecuted": calls_made,
        "fourChannelInvariantsVerified": four_channel_ok,
        "errors": errors,
    }


def run_max_rounds_test(adapter: ControlledToolAdapter, runtime: Runtime, node_id: str, run_id: str) -> bool:
    """Verify max_rounds enforcement."""
    config = ToolSessionConfig(max_tool_rounds=2)
    session = adapter.start_tool_session(node_id, config=config)

    try:
        adapter.call_tool_in_session(session, "read_file", {"path": "hello.txt"})
        adapter.call_tool_in_session(session, "read_file", {"path": "hello.txt"})
    except ToolPermissionError:
        return False

    try:
        adapter.call_tool_in_session(session, "read_file", {"path": "hello.txt"})
        return False  # Should have raised
    except ToolPermissionError:
        return session.status == "max_rounds_exceeded"


def run_timeout_test(adapter: ControlledToolAdapter, runtime: Runtime, node_id: str, run_id: str) -> bool:
    """Verify timeout enforcement."""
    config = ToolSessionConfig(session_timeout_seconds=0)
    session = adapter.start_tool_session(node_id, config=config)

    try:
        adapter.call_tool_in_session(session, "read_file", {"path": "hello.txt"})
        return False
    except ToolPermissionError:
        return session.status == "timeout"


def run_illegal_tool_test(adapter: ControlledToolAdapter, runtime: Runtime, node_id: str, run_id: str) -> bool:
    """Verify illegal tool denial."""
    session = adapter.start_tool_session(node_id)

    try:
        adapter.call_tool_in_session(session, "shell", {"command": "whoami"})
        return False
    except ToolPermissionError:
        if session.status != "denied":
            return False
        # Check events for this specific session
        denied_events = _events_of_type(runtime, run_id, "tool_call_denied")
        session_completed = _events_of_type(runtime, run_id, "tool_session_completed")
        # Find the completed event for this session
        for c in session_completed:
            if c.get("sessionId") == session.session_id and c["status"] == "denied":
                return any(d.get("sessionId") == session.session_id for d in denied_events)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 7: E2E tool loop integration test")
    parser.add_argument("--output", required=True, help="Path to write JSON report")
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    registry = AgentRegistry.default()
    all_agents = registry.list_agents()

    details: list[dict] = []
    total_tool_calls = 0
    all_four_channel_ok = True

    with tempfile.TemporaryDirectory(prefix="squad-e2e-") as tmp:
        tmp_path = Path(tmp)
        project = tmp_path / "project"
        project.mkdir()
        (project / "hello.txt").write_text("hello world", encoding="utf-8")
        (project / "src").mkdir()
        (project / "src" / "main.py").write_text("print('hello')", encoding="utf-8")
        (project / "README.md").write_text("# E2E Test Project", encoding="utf-8")
        (project / "reports").mkdir()
        (project / "reports" / "summary.md").write_text("# Summary", encoding="utf-8")
        (project / "project-docs").mkdir()
        (project / "project-docs" / "spec.md").write_text("# Spec", encoding="utf-8")
        (project / "tests").mkdir()
        (project / "tests" / "test_main.py").write_text("def test_pass(): pass", encoding="utf-8")
        (project / "release").mkdir()
        (project / "release" / "notes.md").write_text("# Release Notes", encoding="utf-8")

        squad_dir = project / ".squad"
        runtime = Runtime.create(squad_dir)
        run = runtime.create_run("Phase 7 E2E tool loop integration")

        test_commands = {"echo_test": ["echo", "test passed"]}
        adapter = ControlledToolAdapter(runtime, project, registry, test_commands=test_commands)

        # --- Per-agent sessions ---
        for agent in all_agents:
            try:
                node = runtime.create_node(
                    run.id,
                    f"E2E test for {agent.agent_id}",
                    "backend",
                    agent.agent_id,
                    checkpoint_id="ckp-1",
                )
                runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")

                result = run_agent_session(adapter, runtime, node.id, agent.agent_id, run.id)
                total_tool_calls += result["callsExecuted"]
                if not result["fourChannelInvariantsVerified"]:
                    all_four_channel_ok = False
                details.append(result)
            except Exception as exc:
                all_four_channel_ok = False
                details.append({
                    "agentId": agent.agent_id,
                    "status": "error",
                    "callsExecuted": 0,
                    "fourChannelInvariantsVerified": False,
                    "errors": [str(exc)],
                })

        # --- Max rounds enforcement test ---
        max_rounds_node = runtime.create_node(
            run.id, "Max rounds test", "backend", "backend-architect", checkpoint_id="ckp-1"
        )
        runtime.transition_node(max_rounds_node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
        max_rounds_ok = run_max_rounds_test(adapter, runtime, max_rounds_node.id, run.id)

        # --- Timeout enforcement test ---
        timeout_node = runtime.create_node(
            run.id, "Timeout test", "backend", "backend-architect", checkpoint_id="ckp-1"
        )
        runtime.transition_node(timeout_node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
        timeout_ok = run_timeout_test(adapter, runtime, timeout_node.id, run.id)

        # --- Illegal tool denial test ---
        illegal_node = runtime.create_node(
            run.id, "Illegal tool test", "backend", "backend-architect", checkpoint_id="ckp-1"
        )
        runtime.transition_node(illegal_node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
        illegal_ok = run_illegal_tool_test(adapter, runtime, illegal_node.id, run.id)

        runtime.close()

    # --- Build report ---
    overall_status = (
        "PASS" if (all_four_channel_ok and max_rounds_ok and timeout_ok and illegal_ok) else "FAIL"
    )

    report = {
        "schemaVersion": "1.0",
        "generatedAt": datetime.now(UTC).isoformat(),
        "status": overall_status,
        "agentsTested": len(all_agents),
        "toolSessionsCompleted": len(details),
        "toolCallsExecuted": total_tool_calls,
        "fourChannelInvariantsVerified": all_four_channel_ok,
        "maxRoundsEnforcementVerified": max_rounds_ok,
        "timeoutEnforcementVerified": timeout_ok,
        "illegalToolDenialVerified": illegal_ok,
        "details": details,
    }

    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Report written to {output_path}")
    print(f"Status: {overall_status}")
    print(f"Agents tested: {len(all_agents)}")
    print(f"Tool calls executed: {total_tool_calls}")
    print(f"Four-channel invariants: {'OK' if all_four_channel_ok else 'FAIL'}")
    print(f"Max rounds enforcement: {'OK' if max_rounds_ok else 'FAIL'}")
    print(f"Timeout enforcement: {'OK' if timeout_ok else 'FAIL'}")
    print(f"Illegal tool denial: {'OK' if illegal_ok else 'FAIL'}")

    sys.exit(0 if overall_status == "PASS" else 1)


if __name__ == "__main__":
    main()
