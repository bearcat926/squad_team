"""Unit tests for the Workspace class."""

from __future__ import annotations

import json
from pathlib import Path

from squad_runtime.providers.workspace import Workspace


def test_workspace_creates_dispatch_dir(tmp_path: Path):
    workspace = Workspace(tmp_path / ".squad", "run-1", "dispatch-1")
    assert workspace.dispatch_dir.exists()
    assert workspace.dispatch_dir == tmp_path / ".squad" / "runs" / "run-1" / "dispatches" / "dispatch-1"


def test_workspace_properties_return_correct_paths(tmp_path: Path):
    workspace = Workspace(tmp_path / ".squad", "run-1", "dispatch-1")
    assert workspace.context_path.name == "context.json"
    assert workspace.prompt_path.name == "prompt.md"
    assert workspace.schema_path.name == "agent-result.schema.json"
    assert workspace.stdout_path.name == "stdout.log"
    assert workspace.stderr_path.name == "stderr.log"
    assert workspace.final_result_path.name == "final-result.json"
    assert workspace.timeout_path.name == "timeout.json"
    assert workspace.health_path.name == "provider-health.json"


def test_workspace_write_prompt(tmp_path: Path):
    workspace = Workspace(tmp_path / ".squad", "run-1", "dispatch-1")
    workspace.write_prompt("Hello agent")
    assert workspace.prompt_path.read_text(encoding="utf-8") == "Hello agent"


def test_workspace_write_stdout_stderr(tmp_path: Path):
    workspace = Workspace(tmp_path / ".squad", "run-1", "dispatch-1")
    workspace.write_stdout("output text")
    workspace.write_stderr("error text")
    assert workspace.stdout_path.read_text(encoding="utf-8") == "output text"
    assert workspace.stderr_path.read_text(encoding="utf-8") == "error text"


def test_workspace_write_timeout(tmp_path: Path):
    workspace = Workspace(tmp_path / ".squad", "run-1", "dispatch-1")
    workspace.write_timeout(600.0)
    data = json.loads(workspace.timeout_path.read_text(encoding="utf-8"))
    assert data["timeoutSec"] == 600.0


def test_workspace_write_schema(tmp_path: Path):
    workspace = Workspace(tmp_path / ".squad", "run-1", "dispatch-1")
    schema = {"type": "object", "required": ["taskNodeId"]}
    workspace.write_schema(schema)
    data = json.loads(workspace.schema_path.read_text(encoding="utf-8"))
    assert data["type"] == "object"
