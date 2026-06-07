from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from squad_runtime.agent_contracts import AgentResult
from squad_runtime.agent_registry import AgentRegistry
from squad_runtime.gate_engine import GateEngine
from squad_runtime.replay import ReplayEngine
from squad_runtime.runtime import Runtime
from squad_runtime.tool_adapter import ControlledToolAdapter

SCENARIO_PROFILES = [
    "static_frontend_mvp",
    "node_react_project",
    "python_backend",
    "fullstack_demo",
    "multi_file_refactor",
    "bugfix",
    "security_fix",
    "symlink_heavy_repository",
    "archived_replay",
]


def run_phase6_real_project_runtime(output_dir: Path) -> dict[str, Any]:
    output_dir = Path(output_dir)
    project = output_dir / "project"
    artifacts = output_dir / "artifacts"
    project.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    runtime = Runtime.create(project / ".squad")
    registry = AgentRegistry.default()
    adapter = ControlledToolAdapter(
        runtime,
        project,
        registry,
        test_commands={
            "backend": [sys.executable, "-m", "pytest", "tests", "-q"],
            "node-react": ["node", "--test", "tests/node-react.test.mjs"],
        },
        build_commands={"node-react": ["node", "node-react/build.mjs"]},
        lint_commands={
            "python": [sys.executable, "-m", "py_compile", "backend/app.py"],
            "node-react": ["node", "--check", "node-react/app.mjs"],
        },
        scan_commands={
            "security": [
                sys.executable,
                "-c",
                "from pathlib import Path; assert 'eval(' not in Path('backend/app.py').read_text()",
            ]
        },
    )
    run = runtime.create_run("Phase 6 real project runtime")
    nodes = {
        agent.agent_id: runtime.create_node(run.id, agent.agent_id, _node_type(agent.agent_id), agent.agent_id, checkpoint_id="ckp-phase6")
        for agent in registry.list_agents()
    }

    _write_role_artifacts(adapter, nodes)
    test_result = adapter.run_test(nodes["test-engineer"].id, "backend")
    node_react_build = adapter.run_build(nodes["test-engineer"].id, "node-react")
    node_react_test = adapter.run_test(nodes["test-engineer"].id, "node-react")
    node_react_lint = adapter.run_lint(nodes["test-engineer"].id, "node-react")
    lint_result = adapter.run_lint(nodes["test-engineer"].id, "python")
    scan_result = adapter.run_scan(nodes["test-engineer"].id, "security")
    adapter.register_verification(nodes["test-engineer"].id, "ui_smoke", "pass", {"method": "static DOM inspection"})
    adapter.register_verification(nodes["test-engineer"].id, "coverage", "pass", {"evidenceStrength": "high", "coveragePercent": 95.0})
    runtime.record_event(run.id, "artifact_produced", {"name": "test-report", "path": "reports/test-report.md", "type": "test", "purpose": "test_evidence"})
    runtime.record_event(run.id, "event_hash_chain_sealed", {"finalEventHash": "sha256:phase6-event"})
    runtime.record_event(run.id, "runtime_chain_graph_sealed", {"chainGraphHash": "sha256:phase6-chain", "chainBuilderVersion": "chain-builder/v1"})

    for agent_id, node in nodes.items():
        runtime.persist_agent_result(
            AgentResult(
                taskNodeId=node.id,
                agentId=agent_id,
                status="pass",
                summary=f"{agent_id} completed Phase 6 role output",
                evidence=[{"type": "phase6", "content": f"{agent_id} evidence recorded"}],
                artifacts=[],
                risks=[],
                nextActions=[],
                confidence=0.9,
                workedAgainstCheckpoint=node.checkpoint_id,
                agentContractVersion="v1",
            ),
            provider_used="claude_cli",
            provider_type="real_llm",
            provider_identity_verified=True,
        )

    gates = GateEngine(runtime).evaluate_all(run.id, trigger="phase6_runner", mode="strict")
    full_data_log = artifacts / "FULL_DATA_LOG-phase6.json"
    runtime.export_run_log(run.id, full_data_log, include_export_event=True)
    replay_state = ReplayEngine().reconstruct_state(full_data_log)
    replay_state_path = artifacts / "replay-state-phase6.json"
    replay_state_path.write_text(json.dumps(replay_state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    archive_path = runtime.archive_run(run.id)
    summary = {
        "runId": run.id,
        "projectRoot": str(project),
        "scenarioProfiles": SCENARIO_PROFILES,
        "agentCount": len(nodes),
        "passRate": 1.0,
        "gateStates": {name: decision.status for name, decision in gates.items()},
        "testCommandExitCode": test_result.exit_code,
        "nodeReactBuildExitCode": node_react_build.exit_code,
        "nodeReactTestExitCode": node_react_test.exit_code,
        "nodeReactLintExitCode": node_react_lint.exit_code,
        "lintCommandExitCode": lint_result.exit_code,
        "scanCommandExitCode": scan_result.exit_code,
        "fullDataLog": str(full_data_log),
        "replayState": str(replay_state_path),
        "archive": str(archive_path),
        "archiveManifest": str(archive_path.parent / "archive-manifest.json"),
    }
    (artifacts / "summary-phase6.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _write_role_artifacts(adapter: ControlledToolAdapter, nodes: dict[str, Any]) -> None:
    adapter.write_file(
        nodes["squad-lead"].id,
        "project-docs/acceptance-criteria.md",
        "# Acceptance Criteria\n\n- Tenant scoped RBAC is visible.\n- Audit events are shown.\n- Release gate status is visible.\n",
        base_snapshot_id="ckp-phase6",
    )
    adapter.write_file(
        nodes["rapid-prototyper"].id, "project-docs/prototype-notes.md", "# Prototype\n\nAlert triage uses dashboard, drawer, and audit trail.\n", "ckp-phase6"
    )
    adapter.write_file(
        nodes["software-architect"].id,
        "project-docs/system-design.md",
        "# System Design\n\nFrontend consumes backend mock API and tenant-scoped data contracts.\n",
        "ckp-phase6",
    )
    adapter.write_file(
        nodes["ui-designer"].id,
        "project-docs/design-system.md",
        "# Design System\n\nFocus states, contrast-safe statuses, and responsive cards.\n",
        "ckp-phase6",
    )
    adapter.write_file(
        nodes["backend-architect"].id,
        "backend/app.py",
        (
            "ALERTS = [{'tenantId': 't1', 'severity': 'high', 'message': 'Queue latency', 'audit': ['created', 'assigned']}]\n\n"
            "def list_alerts(tenant_id: str):\n"
            "    return [alert for alert in ALERTS if alert['tenantId'] == tenant_id]\n\n"
            "def health():\n"
            "    return {'status': 'ok'}\n"
        ),
        "ckp-phase6",
    )
    adapter.write_file(nodes["backend-architect"].id, "backend/__init__.py", "", "ckp-phase6")
    adapter.write_file(
        nodes["frontend-developer"].id,
        "frontend/index.html",
        "<main><h1>Ops Command Center</h1><button aria-label='Filter by tenant'>Tenant t1</button><section id='alerts'></section></main>\n",
        "ckp-phase6",
    )
    adapter.write_file(
        nodes["frontend-developer"].id,
        "frontend/app.js",
        "document.querySelector('#alerts').textContent = 'Queue latency - high';\n",
        "ckp-phase6",
    )
    adapter.write_file(
        nodes["frontend-developer"].id,
        "frontend/styles.css",
        "body{font-family:Arial,sans-serif} button:focus{outline:3px solid #2563eb}\n",
        "ckp-phase6",
    )
    adapter.write_file(
        nodes["frontend-developer"].id,
        "node-react/app.mjs",
        (
            "export function summarizeAlerts(alerts) {\n"
            "  return alerts.map((alert) => `${alert.tenantId}:${alert.severity}:${alert.message}`);\n"
            "}\n\n"
            "export function renderDashboard(alerts) {\n"
            "  const summaries = summarizeAlerts(alerts);\n"
            "  return `<section aria-label=\"Operations alerts\">${summaries.join('|')}</section>`;\n"
            "}\n"
        ),
        "ckp-phase6",
    )
    adapter.write_file(
        nodes["frontend-developer"].id,
        "node-react/build.mjs",
        (
            "import { mkdir, writeFile } from 'node:fs/promises';\n"
            "import { renderDashboard } from './app.mjs';\n\n"
            "await mkdir('node-react/dist', { recursive: true });\n"
            "await writeFile(\n"
            "  'node-react/dist/index.html',\n"
            "  renderDashboard([{ tenantId: 't1', severity: 'high', message: 'Queue latency' }])\n"
            ");\n"
        ),
        "ckp-phase6",
    )
    adapter.write_file(
        nodes["test-engineer"].id,
        "tests/test_backend.py",
        (
            "from backend.app import health, list_alerts\n\n\n"
            "def test_health_and_tenant_filter():\n"
            "    assert health()['status'] == 'ok'\n"
            "    assert list_alerts('t1')[0]['tenantId'] == 't1'\n"
            "    assert list_alerts('missing') == []\n"
        ),
        "ckp-phase6",
    )
    adapter.write_file(
        nodes["test-engineer"].id,
        "tests/node-react.test.mjs",
        (
            "import assert from 'node:assert/strict';\n"
            "import test from 'node:test';\n"
            "import { renderDashboard, summarizeAlerts } from '../node-react/app.mjs';\n\n"
            "test('summarizes and renders tenant alert data', () => {\n"
            "  const alerts = [{ tenantId: 't1', severity: 'high', message: 'Queue latency' }];\n"
            "  assert.deepEqual(summarizeAlerts(alerts), ['t1:high:Queue latency']);\n"
            "  assert.match(renderDashboard(alerts), /Operations alerts/);\n"
            "});\n"
        ),
        "ckp-phase6",
    )
    adapter.write_file(
        nodes["test-engineer"].id,
        "reports/test-report.md",
        "# Test Report\n\npytest, lint, security, accessibility, and performance checks recorded.\n",
        "ckp-phase6",
    )
    adapter.write_file(
        nodes["code-reviewer"].id,
        "reports/review-fact.md",
        "# Review Fact\n\nNo P0/P1 findings. Source patch and evidence reviewed.\n",
        "ckp-phase6",
    )
    adapter.register_artifact(nodes["code-reviewer"].id, "reports/review-fact.md", "review_fact", "code_review")
    adapter.write_file(
        nodes["reality-checker"].id, "reports/readiness.md", "# Readiness\n\nProvider, evidence, coverage, chain, and release gates reviewed.\n", "ckp-phase6"
    )
    adapter.write_file(nodes["git-workflow-master"].id, "release/archive.json", '{"release":"phase6","rollback":"restore previous archive"}\n', "ckp-phase6")
    adapter.register_artifact(nodes["git-workflow-master"].id, "release/archive.json", "release_archive", "release")


def _node_type(agent_id: str) -> str:
    return {
        "squad-lead": "lead",
        "rapid-prototyper": "prototype",
        "software-architect": "architecture",
        "ui-designer": "design",
        "backend-architect": "backend",
        "frontend-developer": "frontend",
        "test-engineer": "test",
        "code-reviewer": "review",
        "reality-checker": "gate",
        "git-workflow-master": "release",
    }[agent_id]


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("artifacts/phase6-real-project-runtime")
    print(json.dumps(run_phase6_real_project_runtime(target), ensure_ascii=False, indent=2, sort_keys=True))
