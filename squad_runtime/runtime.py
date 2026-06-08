"""Runtime facade: backward-compatible entry point delegating to services."""

from __future__ import annotations

import contextlib
import uuid
from pathlib import Path
from typing import Any

from .agent_contracts import AgentResult
from .event_store import EventStore
from .infrastructure.database import Database
from .infrastructure.migrations import run_migrations
from .models import SquadRun, TaskNode
from .repositories.artifact_repository import ArtifactRepository
from .repositories.event_repository import EventRepository
from .repositories.gate_repository import GateRepository
from .repositories.node_repository import NodeRepository
from .repositories.run_repository import RunRepository
from .services.agent_result_service import AgentResultService
from .services.archive_service import ArchiveService
from .services.gate_service import GateService
from .services.node_service import NodeService
from .services.run_service import RunService
from .state import NodeStatus


class Runtime:
    """Backward-compatible facade over the service and repository layers."""

    def __init__(self, squad_dir: Path):
        self.squad_dir = Path(squad_dir)
        self.squad_dir.mkdir(parents=True, exist_ok=True)
        (self.squad_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.squad_dir / "checkpoints").mkdir(parents=True, exist_ok=True)
        (self.squad_dir / "runs").mkdir(parents=True, exist_ok=True)
        (self.squad_dir / "rules").mkdir(parents=True, exist_ok=True)
        self.db_path = self.squad_dir / "squad.db"

        # Infrastructure
        self._db = Database(self.db_path)
        self.conn = self._db.conn
        run_migrations(self.conn)
        self.events = EventStore(self.squad_dir, conn=self.conn)

        # Repositories
        self._run_repo = RunRepository(self.conn)
        self._node_repo = NodeRepository(self.conn)
        self._gate_repo = GateRepository(self.conn)
        self._artifact_repo = ArtifactRepository(self.conn)
        self._event_repo = EventRepository(self.events)

        # Services
        self._run_service = RunService(self._run_repo, self.events)
        self._node_service = NodeService(self._node_repo, self._run_repo, self.events)
        self._agent_result_service = AgentResultService(self._artifact_repo, self._node_repo, self.events, self.squad_dir)
        self._gate_service = GateService(self._gate_repo, self.events)
        self._archive_service = ArchiveService(self._run_repo, self._node_repo, self._gate_repo, self._artifact_repo, self.events, self.squad_dir)

    @classmethod
    def create(cls, squad_dir: Path) -> Runtime:
        return cls(squad_dir)

    # --- Run Management ---

    def create_run(
        self,
        goal: str,
        rule_version: str = "v1",
        schema_version: str = "v1",
        agent_contract_version: str = "v1",
    ) -> SquadRun:
        return self._run_service.create_run(goal, rule_version, schema_version, agent_contract_version)

    def get_run(self, run_id: str) -> SquadRun:
        return self._run_service.get_run(run_id)

    def list_runs(self) -> list[SquadRun]:
        return self._run_service.list_runs()

    # --- Node Management ---

    def create_node(self, run_id: str, title: str, node_type: str, owner_agent_id: str, checkpoint_id: str = "ckp-1") -> TaskNode:
        return self._node_service.create_node(run_id, title, node_type, owner_agent_id, checkpoint_id)

    def get_node(self, node_id: str) -> TaskNode:
        return self._node_service.get_node(node_id)

    def list_nodes(self, run_id: str) -> list[TaskNode]:
        return self._node_service.list_nodes(run_id)

    def transition_node(
        self,
        node_id: str,
        from_status: NodeStatus,
        to_status: NodeStatus,
        reason: str,
        blocked_reason_code: str | None = None,
        metadata: dict[str, Any] | None = None,
        expected_run_version: int | None = None,
    ) -> TaskNode:
        return self._node_service.transition_node(
            node_id,
            from_status,
            to_status,
            reason,
            blocked_reason_code=blocked_reason_code,
            metadata=metadata,
            expected_run_version=expected_run_version,
        )

    # --- Agent Results ---

    def apply_agent_result(self, result: AgentResult) -> str:
        return self._agent_result_service.apply_agent_result(result, self.transition_node)

    def persist_agent_result(
        self,
        result: AgentResult,
        provider_used: str,
        provider_type: str = "deterministic",
        provider_identity_verified: bool = False,
        provider_fallback_triggered: bool = False,
        fallback_reason: str | None = None,
        synthetic: bool = False,
    ) -> str:
        return self._agent_result_service.persist_agent_result(
            result,
            provider_used,
            provider_type,
            provider_identity_verified,
            provider_fallback_triggered,
            fallback_reason,
            synthetic,
        )

    def list_agent_results(self, run_id: str) -> list[dict[str, Any]]:
        return self._artifact_repo.list_agent_results(run_id)

    def list_evidence_items(self, run_id: str) -> list[dict[str, Any]]:
        return self._artifact_repo.list_evidence_items(run_id)

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        return self._artifact_repo.list_artifacts(run_id)

    # --- Directives ---

    def record_directive(self, run_id: str, message: str, source: str = "user") -> str:
        directive_id = f"directive-{uuid.uuid4().hex[:12]}"
        self._artifact_repo.insert_directive(directive_id, run_id, source, message)
        self.events.append(
            run_id,
            "directive_recorded",
            {"directiveId": directive_id, "source": source, "message": message},
            critical=True,
        )
        return directive_id

    # --- Gates ---

    def upsert_gate_state(self, run_id: str, gate_name: str, status: str, reason: str, blocked_reason_code: str | None = None) -> None:
        self._gate_service.upsert_gate_state(run_id, gate_name, status, reason, blocked_reason_code)

    def list_gate_states(self, run_id: str) -> list[dict[str, Any]]:
        return self._gate_service.list_gate_states(run_id)

    # --- Review Findings ---

    def create_review_finding(
        self,
        run_id: str,
        task_node_id: str,
        author_agent_id: str,
        severity: str,
        description: str,
    ) -> str:
        if author_agent_id != "code-reviewer":
            raise PermissionError("Only code-reviewer may create review findings")
        finding_id = f"finding-{uuid.uuid4().hex[:12]}"
        with self.conn:
            self._artifact_repo.insert_review_finding(
                finding_id,
                run_id,
                task_node_id,
                author_agent_id,
                severity,
                description,
            )
            self._artifact_repo.insert_review_finding_history(
                finding_id,
                "created",
                author_agent_id,
                {"severity": severity, "description": description},
            )
        return finding_id

    def supersede_review_finding(
        self,
        finding_id: str,
        author_agent_id: str,
        severity: str,
        description: str,
    ) -> str:
        if author_agent_id != "code-reviewer":
            raise PermissionError("Only code-reviewer may supersede review findings")
        row = self._artifact_repo.get_review_finding(finding_id)
        if row is None:
            raise KeyError(finding_id)
        replacement_id = f"finding-{uuid.uuid4().hex[:12]}"
        with self.conn:
            self._artifact_repo.insert_review_finding(
                replacement_id,
                row["run_id"],
                row["task_node_id"],
                author_agent_id,
                severity,
                description,
            )
            self._artifact_repo.supersede_review_finding(finding_id, replacement_id)
            self._artifact_repo.insert_review_finding_history(
                finding_id,
                "superseded",
                author_agent_id,
                {"replacementId": replacement_id, "severity": severity, "description": description},
            )
        return replacement_id

    def list_review_findings(self, run_id: str) -> list[dict[str, Any]]:
        return self._artifact_repo.list_review_findings(run_id)

    def list_review_finding_history(self, finding_id: str) -> list[dict[str, Any]]:
        return self._artifact_repo.list_review_finding_history(finding_id)

    # --- Events and Artifacts ---

    def record_event(self, run_id: str, event_type: str, payload: dict[str, Any], critical: bool = False) -> dict[str, Any]:
        self._validate_typed_event(event_type, payload)
        event = self.events.append(run_id, event_type, payload, critical=critical)
        return {
            "id": event.id,
            "runId": event.run_id,
            "sequenceNumber": event.sequence_number,
            "type": event.type,
            "payload": event.payload,
            "critical": event.critical,
            "createdAt": event.created_at,
        }

    def record_artifact(self, run_id: str, name: str, path: str, artifact_type: str) -> dict[str, Any]:
        return self.record_event(
            run_id,
            "artifact_produced",
            {
                "name": name,
                "path": path,
                "type": artifact_type,
            },
        )

    # --- Archiving and Export ---

    def archive_run(self, run_id: str) -> Path:
        return self._archive_service.archive_run(run_id)

    def export_run_log(self, run_id: str, output_path: Path, include_export_event: bool = False) -> Path:
        return self._archive_service.export_run_log(run_id, output_path, include_export_event)

    # --- Recovery ---

    def recover_running_dispatches(self) -> list[TaskNode]:
        recovered: list[TaskNode] = []
        nodes = self._node_repo.list_by_status(NodeStatus.RUNNING)
        for node in nodes:
            updated = self.transition_node(node.id, NodeStatus.RUNNING, NodeStatus.AGENT_UNAVAILABLE, "server restart")
            self.events.append(
                updated.run_id,
                "server_restart_dispatch_recovery",
                {"nodeId": updated.id, "ownerAgentId": updated.owner_agent_id},
                critical=True,
            )
            recovered.append(updated)
        return recovered

    # --- Lifecycle ---

    def close(self) -> None:
        self.events.close()
        self.conn.close()

    def __enter__(self) -> Runtime:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.close()

    # --- Private helpers ---

    def _validate_typed_event(self, event_type: str, payload: dict[str, Any]) -> None:
        required = {
            "llm_session_started": {"dispatchId", "agentId"},
            "llm_session_completed": {"dispatchId", "agentId"},
            "agent_result_submitted": {"taskNodeId", "agentId", "status"},
            "tool_permission_denied": {"nodeId", "agentId", "path", "reason"},
            "gate_decision": {"gateName", "status", "reason"},
            "artifact_produced": {"name", "path", "type"},
            "provider_fallback_triggered": {"nodeId", "agentId", "primaryProvider", "fallbackProvider", "reason"},
        }.get(event_type)
        if required is None:
            return
        missing = sorted(required - payload.keys())
        if missing:
            raise ValueError(f"{event_type} missing required fields: {', '.join(missing)}")

    def _node_to_dict(self, node: TaskNode) -> dict[str, Any]:
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
