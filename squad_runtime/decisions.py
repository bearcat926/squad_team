from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .agent_registry import AgentRegistry
from .runtime import Runtime
from .state import NodeStatus


ALLOWED_OPS = {"create_node", "update_node", "cancel_node", "mark_stale", "reroute"}
ALLOWED_NODE_TYPES = {"lead", "prototype", "architecture", "design", "backend", "frontend", "test", "review", "gate", "release"}


@dataclass(frozen=True)
class LeadDecisionChangeSet:
    operations: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class DecisionDryRunResult:
    accepted: bool
    errors: list[str]
    simulated_operations: list[dict[str, Any]]


class DecisionDryRun:
    def __init__(self, runtime: Runtime, registry: AgentRegistry):
        self.runtime = runtime
        self.registry = registry

    def validate(self, run_id: str, change_set: LeadDecisionChangeSet) -> DecisionDryRunResult:
        errors: list[str] = []
        seen_creates: set[tuple[str, str]] = set()
        for operation in change_set.operations:
            op = operation.get("op")
            if op not in ALLOWED_OPS:
                errors.append("invalid_operation")
                continue
            if op == "create_node":
                node_type = operation.get("nodeType")
                owner = operation.get("ownerAgentId")
                title = operation.get("title")
                if node_type not in ALLOWED_NODE_TYPES:
                    errors.append("invalid_node_type")
                if not owner or not self.registry.has(owner):
                    errors.append("unknown_owner")
                identity = (str(title), str(owner))
                if identity in seen_creates:
                    errors.append("duplicate_node")
                seen_creates.add(identity)
            if op in {"cancel_node", "mark_stale", "update_node", "reroute"}:
                node_id = operation.get("nodeId")
                if not node_id:
                    errors.append("missing_node_id")
                    continue
                try:
                    node = self.runtime.get_node(str(node_id))
                except KeyError:
                    errors.append("unknown_node")
                    continue
                if node.run_id != run_id:
                    errors.append("node_run_mismatch")
                if node.status == NodeStatus.DONE and op in {"mark_stale", "update_node", "reroute"}:
                    errors.append("done_node_protected")
        accepted = not errors
        if not accepted:
            self.runtime.events.append(
                run_id,
                "decision_rejected",
                {"errors": sorted(set(errors)), "operations": change_set.operations},
                critical=True,
            )
        return DecisionDryRunResult(accepted=accepted, errors=sorted(set(errors)), simulated_operations=change_set.operations)
