from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .gate_engine import GateEngine
from .lead_decision import LeadDecisionEngine
from .models import SquadEvent, SquadRun, TaskNode
from .runtime import Runtime
from .security import token_matches


class CreateRunRequest(BaseModel):
    goal: str


class DirectiveRequest(BaseModel):
    message: str


def create_app(squad_dir: Path | None = None) -> FastAPI:
    base_dir = Path(squad_dir or ".squad")
    app = FastAPI(title="Squad Runtime", version="0.1.0")
    web_dir = Path(__file__).parent / "web"
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    def runtime():
        rt = Runtime.create(base_dir)
        try:
            yield rt
        finally:
            rt.close()

    def require_token(x_squad_token: str | None = Header(default=None, alias="X-Squad-Token")) -> None:
        if not token_matches(base_dir, x_squad_token):
            raise HTTPException(status_code=401, detail="Invalid or missing squad token")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def web_index() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    @app.post("/api/runs", dependencies=[Depends(require_token)])
    def create_run(request: CreateRunRequest, rt: Runtime = Depends(runtime)) -> dict[str, Any]:
        return _run_to_dict(rt.create_run(request.goal))

    @app.get("/api/runs")
    def list_runs(rt: Runtime = Depends(runtime)) -> dict[str, Any]:
        return {"runs": [_run_to_dict(run) for run in rt.list_runs()]}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, rt: Runtime = Depends(runtime)) -> dict[str, Any]:
        return _run_to_dict(rt.get_run(run_id))

    @app.get("/api/runs/{run_id}/nodes")
    def list_nodes(run_id: str, rt: Runtime = Depends(runtime)) -> dict[str, Any]:
        return {"nodes": [_node_to_dict(node) for node in rt.list_nodes(run_id)]}

    @app.get("/api/runs/{run_id}/events")
    def list_events(run_id: str, cursor: int | None = None, limit: int = 100, rt: Runtime = Depends(runtime)) -> dict[str, Any]:
        page = rt.events.query(run_id, cursor=cursor, limit=limit)
        return {"events": [_event_to_dict(event) for event in page.events], "nextCursor": page.next_cursor}

    @app.post("/api/runs/{run_id}/directives", dependencies=[Depends(require_token)])
    def record_directive(run_id: str, request: DirectiveRequest, rt: Runtime = Depends(runtime)) -> dict[str, Any]:
        decision = LeadDecisionEngine(rt).apply_directive(run_id, request.message)
        return {
            "decision": {
                "directiveId": decision.directive_id,
                "bypassAttempt": decision.bypass_attempt,
                "actions": decision.actions,
            }
        }

    @app.get("/api/runs/{run_id}/gates")
    def get_gates(run_id: str, rt: Runtime = Depends(runtime)) -> dict[str, Any]:
        return {"gates": rt.list_gate_states(run_id)}

    @app.post("/api/runs/{run_id}/gates/evaluate", dependencies=[Depends(require_token)])
    def evaluate_gates(run_id: str, rt: Runtime = Depends(runtime)) -> dict[str, Any]:
        decisions = GateEngine(rt).evaluate_all(run_id)
        return {"gates": {name: decision.__dict__ for name, decision in decisions.items()}}

    @app.post("/api/runs/{run_id}/archive", dependencies=[Depends(require_token)])
    def archive_run(run_id: str, rt: Runtime = Depends(runtime)) -> dict[str, str]:
        archive_path = rt.archive_run(run_id)
        return {"archivePath": str(archive_path)}

    return app


def _run_to_dict(run: SquadRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "goal": run.goal,
        "status": run.status,
        "version": run.version,
        "ruleVersion": run.rule_version,
        "schemaVersion": run.schema_version,
        "agentContractVersion": run.agent_contract_version,
    }


def _node_to_dict(node: TaskNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "runId": node.run_id,
        "title": node.title,
        "type": node.type,
        "ownerAgentId": node.owner_agent_id,
        "status": node.status.value,
        "blockedReasonCode": node.blocked_reason_code,
        "checkpointId": node.checkpoint_id,
        "replacedByNodeId": node.replaced_by_node_id,
    }


def _event_to_dict(event: SquadEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "runId": event.run_id,
        "sequenceNumber": event.sequence_number,
        "type": event.type,
        "payload": event.payload,
        "critical": event.critical,
        "createdAt": event.created_at,
    }
