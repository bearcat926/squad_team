"""Prompt builder for provider dispatches."""

from __future__ import annotations

import json
from typing import Any


class PromptBuilder:
    """Builds the prompt text sent to a provider subprocess."""

    def build(self, context: Any) -> str:
        """Build a prompt from an AgentContextBundle."""
        base_snapshot_id = getattr(context, "base_snapshot_id", context.checkpoint_id)
        result_snapshot_id = getattr(context, "result_snapshot_id", None)
        return (
            "You are the configured Squad Runtime agent. Return exactly one top-level JSON object matching AgentResult.\n"
            "Do not include Markdown fences, commentary, or multiple JSON objects.\n"
            "Do not inspect files, claim to read files, or emit tool calls; use only the context in this prompt.\n"
            "Do not ask for more context. The task, identifiers, checkpoint, and required JSON shape are provided below.\n"
            "For this provider dispatch, the required runtime output is AgentResult even if the agent profile has a different planning contract.\n"
            "Do not mention or use LeadDecisionChangeSet in this dispatch result; return AgentResult only.\n"
            "Do not return status pass for acknowledgement-only output. A pass requires a role-specific conclusion supported by "
            "runtime facts, dependency summaries, or the task itself.\n"
            "Phrases like 'task acknowledged', 'ready to proceed', or 'waiting for upstream deliverables' are not sufficient "
            "for pass; return status blocked when that is all you can conclude.\n"
            "For implementation, testing, review, release, or coverage work, include concrete evidence and artifact references "
            "when available; if required deliverables are unavailable, return status blocked.\n"
            "Return immediately after the JSON object.\n"
            f"Agent: {context.agent_id}\n"
            f"Role: {context.role}\n"
            f"Task Node ID: {context.task_node_id}\n"
            f"Task: {context.task_goal}\n"
            f"Checkpoint: {context.checkpoint_id}\n"
            f"Base Snapshot ID: {base_snapshot_id}\n"
            f"Result Snapshot ID: {result_snapshot_id or 'pending'}\n"
            "Runtime Output Contract: AgentResult\n"
            f"Forbidden paths: {', '.join(context.forbidden_paths)}\n"
            "Runtime facts available to this dispatch:\n"
            f"{json.dumps(context.runtime_facts, ensure_ascii=False, sort_keys=True)}\n"
            "Prior dependency summaries available to this dispatch:\n"
            f"{json.dumps(context.dependency_summaries, ensure_ascii=False, sort_keys=True)}\n"
            "Use the runtime facts and dependency summaries as the authoritative evidence source for this dispatch.\n"
            "If the provided facts are sufficient for your role-specific acceptance decision, return status pass.\n"
            "Required JSON shape:\n"
            "{\n"
            f'  "taskNodeId": "{context.task_node_id}",\n'
            f'  "agentId": "{context.agent_id}",\n'
            '  "status": "pass|fail|blocked",\n'
            '  "summary": "concise result",\n'
            '  "evidence": [{"type": "agent", "content": "evidence"}],\n'
            '  "artifacts": [],\n'
            '  "risks": [{"level": "low", "description": "risk description"}],\n'
            '  "nextActions": [{"action": "next action", "reason": "why"}],\n'
            '  "confidence": 0.0,\n'
            f'  "workedAgainstCheckpoint": "{context.checkpoint_id}",\n'
            '  "schemaVersion": "agent-result/v1",\n'
            f'  "baseSnapshotId": "{base_snapshot_id}",\n'
            '  "resultSnapshotId": null,\n'
            '  "agentContractVersion": "v1"\n'
            "}\n"
        )
