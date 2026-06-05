from __future__ import annotations

from .models import TaskNode
from .runtime import Runtime
from .state import NodeStatus


class Scheduler:
    """Selects dispatch candidates; execution still goes through Agent Runtime Adapter."""

    def __init__(self, runtime: Runtime, global_limit: int = 4, per_agent_type_limit: int = 1):
        self.runtime = runtime
        self.global_limit = global_limit
        self.per_agent_type_limit = per_agent_type_limit

    def select_dispatch_candidates(self, run_id: str) -> list[TaskNode]:
        nodes = self.runtime.list_nodes(run_id)
        running = [node for node in nodes if node.status == NodeStatus.RUNNING]
        slots = max(self.global_limit - len(running), 0)
        if slots == 0:
            return []

        running_by_owner: dict[str, int] = {}
        for node in running:
            running_by_owner[node.owner_agent_id] = running_by_owner.get(node.owner_agent_id, 0) + 1

        candidates: list[TaskNode] = []
        for node in nodes:
            if node.status != NodeStatus.READY:
                continue
            owner_load = running_by_owner.get(node.owner_agent_id, 0)
            if owner_load >= self.per_agent_type_limit:
                continue
            candidates.append(node)
            running_by_owner[node.owner_agent_id] = owner_load + 1
            if len(candidates) >= slots:
                break
        return candidates

    def mark_progress_timeout(self, node_id: str) -> TaskNode:
        node = self.runtime.get_node(node_id)
        return self.runtime.transition_node(node.id, NodeStatus.RUNNING, NodeStatus.PROGRESS_TIMEOUT, "progress timeout")
