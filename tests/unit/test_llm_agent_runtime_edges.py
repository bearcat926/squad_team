from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from squad_runtime.adapter import AgentRuntimeAdapter
from squad_runtime.agent_registry import AgentRegistry
from squad_runtime.cli import app as cli_app
from squad_runtime.providers import FakeCliProvider, ProviderRegistry
from squad_runtime.runtime import Runtime
from squad_runtime.state import NodeStatus


class UnavailableProvider:
    name = "unavailable_cli"

    def health(self):
        return None

    def execute(self, runtime, node, profile, synthetic=False):
        raise RuntimeError("provider unavailable")


def test_adapter_automatic_fallback_records_provider_source(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("fallback")
    node = runtime.create_node(run.id, "Build UI", "frontend", "frontend-developer")
    runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    registry = AgentRegistry.default().with_provider_override(
        "frontend-developer",
        provider="unavailable_cli",
        fallback_provider="fake_cli",
        fallback_mode="automatic",
    )
    providers = ProviderRegistry({"unavailable_cli": UnavailableProvider(), "fake_cli": FakeCliProvider()})

    result = AgentRuntimeAdapter(runtime, registry, providers).dispatch_once(node.id)

    assert result.status == "pass"
    stored = runtime.list_agent_results(run.id)[0]
    assert stored["providerUsed"] == "fake_cli"
    assert stored["providerFallbackTriggered"] is True
    assert stored["fallbackReason"] == "primary_provider_unavailable"
    events = [event.type for event in runtime.events.query(run.id).events]
    assert "provider_fallback_triggered" in events


def test_adapter_denies_forbidden_squad_file_access(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("policy")
    node = runtime.create_node(run.id, "Review", "review", "code-reviewer")
    adapter = AgentRuntimeAdapter(runtime, AgentRegistry.default(), ProviderRegistry({"fake_cli": FakeCliProvider()}))

    allowed = adapter.validate_file_access(node.id, tmp_path / "project" / "app.py", mode="read")
    denied = adapter.validate_file_access(node.id, tmp_path / ".squad" / "token", mode="read")

    assert allowed is True
    assert denied is False
    assert runtime.events.query(run.id).events[-1].type == "tool_permission_denied"


def test_review_findings_are_immutable_and_versioned(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("review")
    node = runtime.create_node(run.id, "Review", "review", "code-reviewer")

    finding_id = runtime.create_review_finding(
        run.id,
        node.id,
        "code-reviewer",
        severity="P1",
        description="Authorization check missing",
    )
    replacement_id = runtime.supersede_review_finding(
        finding_id,
        "code-reviewer",
        severity="P2",
        description="Authorization check documented",
    )

    findings = runtime.list_review_findings(run.id)
    assert findings[0]["status"] == "superseded"
    assert findings[0]["supersededById"] == replacement_id
    assert findings[1]["description"] == "Authorization check documented"
    assert runtime.list_review_finding_history(finding_id)[-1]["action"] == "superseded"


def test_cli_dispatch_once_runs_fake_provider(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert runner.invoke(cli_app, ["init"]).exit_code == 0
        run_result = runner.invoke(cli_app, ["run", "dispatch fake"])
        run_id = json.loads(run_result.stdout)["id"]
        dispatch_result = runner.invoke(cli_app, ["dispatch", run_id, "--once", "--provider", "fake_cli"])

        assert dispatch_result.exit_code == 0
        payload = json.loads(dispatch_result.stdout)
        assert payload["dispatched"] == 1
        assert payload["results"][0]["status"] == "pass"


def test_cli_export_log_final_includes_export_event(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert runner.invoke(cli_app, ["init"]).exit_code == 0
        run_result = runner.invoke(cli_app, ["run", "final export"])
        run_id = json.loads(run_result.stdout)["id"]
        export_path = Path("FULL_DATA_LOG.md")
        export = runner.invoke(cli_app, ["export-log", run_id, "--output", str(export_path), "--final"])

        assert export.exit_code == 0
        assert "log_exported" in export_path.read_text(encoding="utf-8")


def test_p0_typed_event_requires_schema_fields(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert runner.invoke(cli_app, ["init"]).exit_code == 0
        run_result = runner.invoke(cli_app, ["run", "typed events"])
        run_id = json.loads(run_result.stdout)["id"]
        bad = runner.invoke(
            cli_app,
            ["log-event", run_id, "llm_session_started", "--payload-json", '{"agentId":"frontend-developer"}'],
        )

        assert bad.exit_code != 0
        assert "dispatchId" in bad.output
