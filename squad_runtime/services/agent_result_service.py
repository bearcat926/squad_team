"""Service for agent result operations."""

from __future__ import annotations

import uuid
from pathlib import Path

from ..agent_contracts import AgentResult, validate_agent_result
from ..event_store import EventStore
from ..repositories.artifact_repository import ArtifactRepository
from ..repositories.node_repository import NodeRepository
from ..state import NodeStatus


class AgentResultService:
    """Business logic for applying and persisting agent results."""

    def __init__(self, artifact_repo: ArtifactRepository, node_repo: NodeRepository, events: EventStore, squad_dir: Path):
        self._artifact_repo = artifact_repo
        self._node_repo = node_repo
        self._events = events
        self._squad_dir = squad_dir

    def apply_agent_result(self, result: AgentResult, transition_fn) -> str:
        """Apply an agent result: validate and transition node.

        transition_fn is called as transition_node(node_id, from, to, reason, ...)
        to decouple from NodeService circular dependency.
        """
        node = self._node_repo.get(result.taskNodeId)
        if node.status in {NodeStatus.CANCELED, NodeStatus.STALE, NodeStatus.DONE}:
            self._events.append(node.run_id, "stale_advisory", {"nodeId": node.id, "agentId": result.agentId}, critical=True)
            return "stale_advisory"

        validation = validate_agent_result(result, self._squad_dir / "artifacts", node.checkpoint_id)
        if not validation.valid:
            transition_fn(
                node.id,
                node.status,
                NodeStatus.BLOCKED,
                "invalid agent result",
                blocked_reason_code="invalid_agent_result",
                metadata={"errors": validation.errors},
            )
            self._events.append(node.run_id, "invalid_agent_result", {"nodeId": node.id, "errors": validation.errors}, critical=True)
            return "invalid_agent_result"

        target = NodeStatus(result.status)
        if node.status != NodeStatus.RUNNING:
            self._events.append(
                node.run_id,
                "stale_advisory",
                {"nodeId": node.id, "agentId": result.agentId, "actualStatus": node.status.value},
                critical=True,
            )
            return "stale_advisory"
        transition_fn(
            node.id,
            NodeStatus.RUNNING,
            target,
            "agent result",
            blocked_reason_code="gate_dependency_failed" if target == NodeStatus.BLOCKED else None,
        )
        return result.status

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
        node = self._node_repo.get(result.taskNodeId)
        validation = validate_agent_result(result, self._squad_dir / "artifacts", node.checkpoint_id)
        if not validation.valid:
            self._events.append(
                node.run_id,
                "invalid_agent_result",
                {"nodeId": node.id, "agentId": result.agentId, "errors": validation.errors},
                critical=True,
            )
            return "invalid_agent_result"
        result_id = f"agent-result-{uuid.uuid4().hex[:12]}"
        with self._artifact_repo.conn:
            self._artifact_repo.insert_agent_result(
                result_id=result_id,
                run_id=node.run_id,
                result=result,
                provider_used=provider_used,
                provider_type=provider_type,
                provider_identity_verified=provider_identity_verified,
                provider_fallback_triggered=provider_fallback_triggered,
                fallback_reason=fallback_reason,
                synthetic=synthetic,
            )
            for evidence in result.evidence:
                self._artifact_repo.insert_evidence_item(
                    run_id=node.run_id,
                    task_node_id=result.taskNodeId,
                    source_type=evidence.get("type", "agent"),
                    author_agent_id=result.agentId,
                    content=evidence.get("content", ""),
                )
            for artifact in result.artifacts:
                self._artifact_repo.insert_artifact(
                    run_id=node.run_id,
                    task_node_id=result.taskNodeId,
                    name=str(artifact.get("name", "artifact")),
                    path=str(artifact.get("path", "")),
                    artifact_type=str(artifact.get("type", "agent-artifact")),
                    author_agent_id=result.agentId,
                )
        self._events.append(
            node.run_id,
            "agent_result_submitted",
            {
                "agentResultId": result_id,
                "taskNodeId": result.taskNodeId,
                "agentId": result.agentId,
                "status": result.status,
                "providerUsed": provider_used,
                "providerFallbackTriggered": provider_fallback_triggered,
                "fallbackReason": fallback_reason,
                "synthetic": synthetic,
            },
            critical=True,
        )
        return result_id
