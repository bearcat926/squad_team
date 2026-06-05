from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import typer

from .acceptance import AcceptanceReporter
from .adapter import AgentRuntimeAdapter
from .agent_registry import AgentRegistry
from .analytics import AnalyticsEngine
from .api import create_app
from .gate_engine import GateEngine
from .lead_decision import LeadDecisionEngine
from .providers import ProviderRegistry
from .runtime import Runtime
from .scheduler import Scheduler
from .security import initialize_project, read_token, rotate_token
from .services.backup_service import backup, restore
from .state import NodeStatus

app = typer.Typer(help="Local Squad Runtime CLI")
token_app = typer.Typer(help="Token commands")
agents_app = typer.Typer(help="Agent registry and provider commands")
backup_app = typer.Typer(help="Backup and restore commands")


def _squad_dir() -> Path:
    acceptance_root = os.environ.get("SQUAD_ACCEPTANCE_ROOT")
    return Path(acceptance_root).resolve() / ".squad" if acceptance_root else Path.cwd() / ".squad"


def _runtime_home() -> Path:
    configured = os.environ.get("SQUAD_RUNTIME_HOME")
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[1]


def _runtime() -> Runtime:
    return Runtime.create(_squad_dir())


def _echo_json(payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write((text + "\n").encode("utf-8"))
        buffer.flush()
    else:  # pragma: no cover - exercised by Typer's test capture stream.
        sys.stdout.write(text + "\n")


@app.command()
def init() -> None:
    squad_dir = _squad_dir()
    initialization = initialize_project(squad_dir)
    Runtime.create(squad_dir)
    _echo_json(
        {
            "runtimeHome": str(_runtime_home()),
            "squadDir": str(squad_dir),
            "tokenPath": str(squad_dir / "token"),
            "tokenCreated": initialization.token_created,
        }
    )


@app.command(name="run")
def run_command(goal: str) -> None:
    initialize_project(_squad_dir())
    rt = _runtime()
    run = rt.create_run(goal)
    lead_node = rt.create_node(run.id, "Lead planning", "lead", "squad-lead")
    rt.transition_node(lead_node.id, NodeStatus.TODO, NodeStatus.READY, "initial lead planning ready")
    _echo_json({"id": run.id, "goal": run.goal, "status": run.status})


@app.command()
def status() -> None:
    rt = _runtime()
    runs = [{"id": run.id, "goal": run.goal, "status": run.status, "version": run.version} for run in rt.list_runs()]
    _echo_json({"runs": runs})


@app.command()
def send(run_id: str, message: str) -> None:
    rt = _runtime()
    decision = LeadDecisionEngine(rt).apply_directive(run_id, message)
    _echo_json({"directiveId": decision.directive_id, "bypassAttempt": decision.bypass_attempt, "actions": decision.actions})


@app.command("dispatch")
def dispatch(run_id: str, once: bool = typer.Option(False, "--once"), provider: str | None = typer.Option(None, "--provider")) -> None:
    rt = _runtime()
    registry = AgentRegistry.default()
    providers = ProviderRegistry.default()
    scheduler = Scheduler(rt, global_limit=1 if once else 4, per_agent_type_limit=1)
    adapter = AgentRuntimeAdapter(rt, registry, providers)
    candidates = scheduler.select_dispatch_candidates(run_id)
    results = []
    for node in candidates[: 1 if once else len(candidates)]:
        result = adapter.dispatch_once(node.id, provider_override=provider)
        if result is None:
            updated = rt.get_node(node.id)
            results.append(
                {
                    "taskNodeId": updated.id,
                    "agentId": updated.owner_agent_id,
                    "status": updated.status.value,
                    "blockedReasonCode": updated.blocked_reason_code,
                    "result": None,
                }
            )
        else:
            results.append({"taskNodeId": result.taskNodeId, "agentId": result.agentId, "status": result.status, "result": "agent_result"})
        GateEngine(rt).evaluate_all(run_id, trigger="system_dispatch_loop")
    _echo_json({"dispatched": len(results), "results": results})


@app.command("eval-gates")
def eval_gates(run_id: str, gate: str | None = typer.Option(None, "--gate")) -> None:
    rt = _runtime()
    decisions = GateEngine(rt).evaluate_all(run_id, trigger="cli_user")
    if gate:
        decisions = {gate: decisions[gate]}
    _echo_json({"gates": {name: decision.__dict__ for name, decision in decisions.items()}})


@app.command()
def start(host: str = "127.0.0.1", port: int = 8765) -> None:
    initialize_project(_squad_dir())
    import uvicorn

    uvicorn.run(create_app(_squad_dir()), host=host, port=port)


@app.command()
def open(port: int = 8765) -> None:
    _echo_json({"url": f"http://127.0.0.1:{port}"})


@app.command("log-event")
def log_event(
    run_id: str,
    event_type: str,
    payload_json: str = typer.Option("{}", "--payload-json"),
    payload_file: Path | None = typer.Option(None, "--payload-file"),
) -> None:
    raw_payload = payload_file.read_text(encoding="utf-8-sig") if payload_file else payload_json
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"payload must be valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter("payload must decode to a JSON object")
    try:
        event = _runtime().record_event(run_id, event_type, payload)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _echo_json(event)


@app.command("log-artifact")
def log_artifact(
    run_id: str,
    name: str = typer.Option(..., "--name"),
    path: str = typer.Option(..., "--path"),
    artifact_type: str = typer.Option(..., "--type"),
) -> None:
    event = _runtime().record_artifact(run_id, name, path, artifact_type)
    _echo_json(event)


@app.command("export-log")
def export_log(run_id: str, output: Path = typer.Option(..., "--output"), final: bool = typer.Option(False, "--final")) -> None:
    output_path = _runtime().export_run_log(run_id, output, include_export_event=final)
    _echo_json({"outputPath": str(output_path)})


@app.command("acceptance-report")
def acceptance_report(
    run_id: str,
    output: Path = typer.Option(..., "--output"),
    coverage_percent: float | None = typer.Option(None, "--coverage-percent"),
    codebase_memory_status: str | None = typer.Option(None, "--codebase-memory-status"),
    codebase_memory_project: str | None = typer.Option(None, "--codebase-memory-project"),
    codebase_memory_nodes: int | None = typer.Option(None, "--codebase-memory-nodes"),
    codebase_memory_edges: int | None = typer.Option(None, "--codebase-memory-edges"),
    architecture_status: str | None = typer.Option(None, "--architecture-status"),
) -> None:
    rt = _runtime()
    payload = AcceptanceReporter(rt).write_report(
        run_id,
        output,
        coverage_percent=coverage_percent,
        codebase_memory={
            "status": codebase_memory_status,
            "project": codebase_memory_project,
            "nodes": codebase_memory_nodes,
            "edges": codebase_memory_edges,
            "architecture": architecture_status,
        },
    )
    _echo_json({"outputPath": str(output), "conclusion": payload["conclusion"], "risks": payload["risks"]})


@app.command()
def archive(run_id: str) -> None:
    rt = _runtime()
    archive_path = rt.archive_run(run_id)
    _echo_json({"archivePath": str(archive_path)})


@agents_app.command("list")
def agents_list() -> None:
    registry = AgentRegistry.default()
    _echo_json(registry.snapshot())


@agents_app.command("doctor")
def agents_doctor() -> None:
    provider_registry = ProviderRegistry.default()
    results = [health.__dict__ for health in provider_registry.doctor()]
    _echo_json({"providers": results})


@token_app.command("rotate")
def token_rotate() -> None:
    token = rotate_token(_squad_dir())
    _echo_json({"tokenPath": str(_squad_dir() / "token"), "token": token})


@token_app.command("show")
def token_show() -> None:
    _echo_json({"token": read_token(_squad_dir())})


@backup_app.command("backup")
def backup_cmd(
    output: Path = typer.Option(..., "--output", help="Destination path for the .tar.gz archive"),
    include_token: bool = typer.Option(False, "--include-token", help="Include the token file in the backup"),
) -> None:
    """Create a backup archive of the .squad directory."""
    squad_dir = _squad_dir()
    archive_path = backup(squad_dir, output, include_token=include_token)
    _echo_json({"archivePath": str(archive_path), "includeToken": include_token})


@backup_app.command("restore")
def restore_cmd(
    backup_path: Path = typer.Argument(..., help="Path to the .tar.gz backup file"),
    target: Path = typer.Option(..., "--target", help="Directory to restore into"),
) -> None:
    """Restore a backup archive to a target directory."""
    target_dir = restore(backup_path, target)
    _echo_json({"targetDir": str(target_dir)})


@app.command()
def analytics(run_id: str | None = typer.Argument(None, help="Optional run ID to scope analytics")) -> None:
    """Compute and display run analytics summary."""
    rt = _runtime()
    summary = AnalyticsEngine(rt).compute_summary(run_id)
    _echo_json(summary)


app.add_typer(agents_app, name="agents")
app.add_typer(token_app, name="token")
app.add_typer(backup_app, name="backup")


if __name__ == "__main__":
    app()
