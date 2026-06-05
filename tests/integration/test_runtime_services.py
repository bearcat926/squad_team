from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

import squad_runtime.cli as cli_module
from squad_runtime.api import create_app
from squad_runtime.cli import app as cli_app
from squad_runtime.runtime import Runtime
from squad_runtime.scheduler import Scheduler
from squad_runtime.security import initialize_project
from squad_runtime.state import InvalidTransition, NodeStatus


def test_expected_run_version_conflict_records_event(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("versioned transition")
    node = runtime.create_node(run.id, "Backend task", "backend", "backend-architect")

    runtime.transition_node(
        node.id,
        NodeStatus.TODO,
        NodeStatus.READY,
        "ready",
        expected_run_version=0,
    )

    try:
        runtime.transition_node(
            node.id,
            NodeStatus.READY,
            NodeStatus.RUNNING,
            "stale caller",
            expected_run_version=0,
        )
    except InvalidTransition as exc:
        assert "Expected run version" in str(exc)
    else:
        raise AssertionError("version conflict did not fail")

    assert runtime.events.query(run.id).events[-1].type == "transition_conflict"


def test_restart_recovery_marks_running_nodes_unavailable(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("restart recovery")
    node = runtime.create_node(run.id, "Frontend task", "frontend", "frontend-developer")

    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    runtime.transition_node(node.id, NodeStatus.READY, NodeStatus.RUNNING, "dispatch")

    recovered = runtime.recover_running_dispatches()

    assert [item.id for item in recovered] == [node.id]
    assert runtime.get_node(node.id).status == NodeStatus.AGENT_UNAVAILABLE
    assert runtime.events.query(run.id).events[-1].type == "server_restart_dispatch_recovery"


def test_scheduler_respects_global_and_per_agent_limits(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("schedule candidates")
    backend_running = runtime.create_node(run.id, "Backend running", "backend", "backend-architect")
    backend_ready = runtime.create_node(run.id, "Backend ready", "backend", "backend-architect")
    frontend_ready = runtime.create_node(run.id, "Frontend ready", "frontend", "frontend-developer")

    for node in [backend_running, backend_ready, frontend_ready]:
        runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    runtime.transition_node(backend_running.id, NodeStatus.READY, NodeStatus.RUNNING, "dispatch")

    scheduler = Scheduler(runtime, global_limit=4, per_agent_type_limit=1)
    candidates = scheduler.select_dispatch_candidates(run.id)

    assert [node.id for node in candidates] == [frontend_ready.id]


def test_api_requires_token_and_records_bypass_directive(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    token = initialize_project(squad_dir).token
    client = TestClient(create_app(squad_dir))

    denied = client.post("/api/runs", json={"goal": "build without token"})
    assert denied.status_code == 401

    created = client.post("/api/runs", json={"goal": "build"}, headers={"X-Squad-Token": token})
    assert created.status_code == 200
    run_id = created.json()["id"]

    directive = client.post(
        f"/api/runs/{run_id}/directives",
        json={"message": "release_go now"},
        headers={"X-Squad-Token": token},
    )
    assert directive.status_code == 200
    assert directive.json()["decision"]["bypassAttempt"] is True

    events = client.get(f"/api/runs/{run_id}/events", headers={"X-Squad-Token": token}).json()["events"]
    assert "gate_bypass_attempt" in [event["type"] for event in events]


def test_api_serves_readonly_web_ui(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    initialize_project(squad_dir)
    client = TestClient(create_app(squad_dir))

    response = client.get("/")

    assert response.status_code == 200
    assert "Read-only DAG" in response.text
    assert "Send directive to Squad Lead" in response.text


def test_cli_init_run_status_and_archive(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        first_init = runner.invoke(cli_app, ["init"])
        assert first_init.exit_code == 0
        assert json.loads(first_init.stdout)["tokenCreated"] is True
        second_init = runner.invoke(cli_app, ["init"])
        assert second_init.exit_code == 0
        assert json.loads(second_init.stdout)["tokenCreated"] is False
        run_result = runner.invoke(cli_app, ["run", "ship local runtime"])
        assert run_result.exit_code == 0
        run_id = json.loads(run_result.stdout)["id"]

        status_result = runner.invoke(cli_app, ["status"])
        assert status_result.exit_code == 0
        assert run_id in status_result.stdout

        archive_result = runner.invoke(cli_app, ["archive", run_id])
        assert archive_result.exit_code == 0
        archive_path = Path(json.loads(archive_result.stdout)["archivePath"])
        assert archive_path.exists()
        assert json.loads(archive_path.read_text(encoding="utf-8"))["run"]["id"] == run_id


def test_cli_respects_acceptance_root_and_reports_runtime_home(tmp_path: Path):
    runner = CliRunner()
    acceptance_root = tmp_path / "acceptance-target"
    runtime_home = tmp_path / "runtime-home"
    acceptance_root.mkdir()
    runtime_home.mkdir()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli_app,
            ["init"],
            env={
                "SQUAD_ACCEPTANCE_ROOT": str(acceptance_root),
                "SQUAD_RUNTIME_HOME": str(runtime_home),
            },
        )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert Path(payload["squadDir"]) == acceptance_root / ".squad"
    assert Path(payload["runtimeHome"]) == runtime_home
    assert (acceptance_root / ".squad" / "token").exists()


def test_cli_dispatch_reports_explicit_failure_record_when_provider_returns_no_result(tmp_path: Path, monkeypatch):
    class BrokenProvider:
        def execute(self, runtime: Runtime, node, profile):
            current = runtime.get_node(node.id)
            runtime.transition_node(current.id, NodeStatus.READY, NodeStatus.RUNNING, "broken dispatch")
            runtime.transition_node(current.id, NodeStatus.RUNNING, NodeStatus.AGENT_UNAVAILABLE, "provider unavailable")
            runtime.events.append(
                node.run_id,
                "agent_timeout",
                {"nodeId": node.id, "agentId": profile.agent_id, "provider": "broken"},
                critical=True,
            )
            return None

    class BrokenProviderRegistry:
        def __init__(self):
            self.providers = {"broken": BrokenProvider()}

        def get(self, provider_name: str):
            return self.providers[provider_name]

    monkeypatch.setattr(cli_module.ProviderRegistry, "default", classmethod(lambda cls: BrokenProviderRegistry()))
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert runner.invoke(cli_app, ["init"]).exit_code == 0
        run_result = runner.invoke(cli_app, ["run", "dispatch failure"])
        run_id = json.loads(run_result.stdout)["id"]

        dispatch_result = runner.invoke(cli_app, ["dispatch", run_id, "--once", "--provider", "broken"])

    assert dispatch_result.exit_code == 0
    payload = json.loads(dispatch_result.stdout)
    assert payload["dispatched"] == 1
    assert payload["results"][0]["result"] is None
    assert payload["results"][0]["status"] == "agent_unavailable"


def test_cli_log_event_artifact_and_export_log(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert runner.invoke(cli_app, ["init"]).exit_code == 0
        run_result = runner.invoke(cli_app, ["run", "audit command run"])
        assert run_result.exit_code == 0
        run_id = json.loads(run_result.stdout)["id"]

        event_result = runner.invoke(
            cli_app,
            [
                "log-event",
                run_id,
                "agent_operation",
                "--payload-json",
                '{"agentId":"frontend-developer","operation":"rendered dashboard"}',
            ],
        )
        assert event_result.exit_code == 0
        assert json.loads(event_result.stdout)["type"] == "agent_operation"
        payload_file = Path("payload.json")
        payload_file.write_bytes(b"\xef\xbb\xbf" + b'{"agentId":"test-engineer","operation":"payload file log"}')
        file_event_result = runner.invoke(
            cli_app,
            [
                "log-event",
                run_id,
                "agent_operation",
                "--payload-file",
                str(payload_file),
            ],
        )
        assert file_event_result.exit_code == 0
        assert json.loads(file_event_result.stdout)["payload"]["agentId"] == "test-engineer"

        artifact_result = runner.invoke(
            cli_app,
            [
                "log-artifact",
                run_id,
                "--name",
                "dashboard",
                "--path",
                "index.html",
                "--type",
                "mvp-file",
            ],
        )
        assert artifact_result.exit_code == 0
        assert json.loads(artifact_result.stdout)["type"] == "artifact_produced"

        export_path = Path("FULL_DATA_LOG.md")
        export_result = runner.invoke(cli_app, ["export-log", run_id, "--output", str(export_path)])
        assert export_result.exit_code == 0
        assert export_path.exists()
        exported = export_path.read_text(encoding="utf-8")
        assert "# Squad Runtime Full Data Log" in exported
        assert "agent_operation" in exported
        assert "artifact_produced" in exported
        assert "frontend-developer" in exported
