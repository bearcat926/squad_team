from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .agent_registry import AgentProfile
from .runtime import Runtime


class _AgentRegistryLike(Protocol):
    def get(self, agent_id: str) -> AgentProfile: ...


@dataclass(frozen=True)
class AgentContextBundle:
    agent_id: str
    role: str
    profile_version: str
    task_node_id: str
    task_goal: str
    checkpoint_id: str
    output_contract: str
    allowed_tools: tuple[str, ...]
    allowed_read_paths: tuple[str, ...]
    allowed_write_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    dependency_summaries: list[dict[str, Any]] = field(default_factory=list)
    runtime_facts: list[dict[str, Any]] = field(default_factory=list)
    memory_policy: str = "dispatch_isolated"


class AgentContextBuilder:
    def __init__(self, runtime: Runtime, registry: _AgentRegistryLike):
        self.runtime = runtime
        self.registry = registry

    def build(self, node_id: str) -> AgentContextBundle:
        node = self.runtime.get_node(node_id)
        profile = self.registry.get(node.owner_agent_id)
        dependency_summaries = []
        for result in self.runtime.list_agent_results(node.run_id):
            if result["taskNodeId"] == node_id:
                continue
            dependency_summaries.append(
                {
                    "agent_id": result["agentId"],
                    "task_node_id": result["taskNodeId"],
                    "status": result["status"],
                    "output_summary": result["summary"],
                    "artifacts": result["artifacts"],
                    "risks": result["risks"],
                    "next_actions": result["nextActions"],
                }
            )
        runtime_facts = [
            {
                "type": event.type,
                "payload": event.payload,
            }
            for event in self.runtime.events.query(node.run_id, limit=100000).events
            if event.type in {"verification_result", "coverage_lane_update", "skill_usage"}
        ]
        return AgentContextBundle(
            agent_id=profile.agent_id,
            role=profile.role,
            profile_version=profile.profile_version,
            task_node_id=node.id,
            task_goal=node.title,
            checkpoint_id=node.checkpoint_id,
            # AgentRuntimeAdapter dispatches always return AgentResult. LeadDecisionChangeSet
            # remains a Lead planning contract, not a provider dispatch output contract.
            output_contract="AgentResult",
            allowed_tools=profile.allowed_tools,
            allowed_read_paths=profile.allowed_read_paths,
            allowed_write_paths=profile.allowed_write_paths,
            forbidden_paths=profile.forbidden_paths,
            dependency_summaries=dependency_summaries,
            runtime_facts=runtime_facts,
        )
