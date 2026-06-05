"""Service for node lifecycle operations."""

from __future__ import annotations

import uuid
from typing import Any

from ..event_store import EventStore
from ..models import TaskNode
from ..repositories.node_repository import NodeRepository
from ..repositories.run_repository import RunRepository
from ..state import BLOCKED_REASON_CODES, InvalidTransition, NodeStatus, ensure_transition_allowed


class NodeService:
    """Business logic for creating, reading, transitioning nodes."""

    def __init__(self, node_repo: NodeRepository, run_repo: RunRepository, events: EventStore):
        self._node_repo = node_repo
        self._run_repo = run_repo
        self._events = events

    def create_node(self, run_id: str, title: str, node_type: str, owner_agent_id: str, checkpoint_id: str = "ckp-1") -> TaskNode:
        node_id = f"node-{uuid.uuid4().hex[:12]}"
        self._node_repo.insert(node_id, run_id, title, node_type, owner_agent_id, NodeStatus.TODO, checkpoint_id)
        self._events.append(run_id, "node_created", {"nodeId": node_id, "type": node_type}, critical=True)
        return self.get_node(node_id)

    def get_node(self, node_id: str) -> TaskNode:
        return self._node_repo.get(node_id)

    def list_nodes(self, run_id: str) -> list[TaskNode]:
        return self._node_repo.list_by_run(run_id)

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
        if to_status == NodeStatus.BLOCKED and not blocked_reason_code:
            raise ValueError("blockedReasonCode is required when node status becomes blocked")
        if blocked_reason_code and blocked_reason_code not in BLOCKED_REASON_CODES:
            raise ValueError(f"Unknown blockedReasonCode: {blocked_reason_code}")
        ensure_transition_allowed(from_status, to_status)
        node = self.get_node(node_id)
        run = self._run_repo.get(node.run_id)
        if expected_run_version is not None and run.version != expected_run_version:
            self._events.append(
                node.run_id,
                "transition_conflict",
                {
                    "nodeId": node_id,
                    "expectedRunVersion": expected_run_version,
                    "actualRunVersion": run.version,
                    "to": to_status.value,
                },
                critical=True,
            )
            raise InvalidTransition(f"Expected run version {expected_run_version}, got {run.version}")
        if node.status != from_status:
            self._events.append(
                node.run_id,
                "transition_conflict",
                {"nodeId": node_id, "expected": from_status.value, "actual": node.status.value, "to": to_status.value},
                critical=True,
            )
            raise InvalidTransition(f"Expected {from_status.value}, got {node.status.value}")

        self._node_repo.update_status(node_id, from_status, to_status, blocked_reason_code)
        self._run_repo.increment_version(node.run_id)
        self._events.append(
            node.run_id,
            "node_status_changed",
            {
                "nodeId": node_id,
                "from": from_status.value,
                "to": to_status.value,
                "reason": reason,
                "blockedReasonCode": blocked_reason_code,
                "metadata": metadata or {},
            },
            critical=True,
        )
        return self.get_node(node_id)
