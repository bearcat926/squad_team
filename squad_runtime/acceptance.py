from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agent_registry import AgentRegistry
from .runtime import Runtime
from .state import NodeStatus


TERMINAL_NODE_STATUSES = {
    NodeStatus.PASS.value,
    NodeStatus.FAIL.value,
    NodeStatus.BLOCKED.value,
    NodeStatus.AGENT_UNAVAILABLE.value,
    NodeStatus.CANCELED.value,
    NodeStatus.STALE.value,
    NodeStatus.DONE.value,
}


class AcceptanceReporter:
    def __init__(self, runtime: Runtime):
        self.runtime = runtime
        self.acceptance_dir = runtime.squad_dir / "acceptance"
        self.baseline_path = self.acceptance_dir / "coverage-baseline.json"

    def write_report(
        self,
        run_id: str,
        output_path: Path,
        coverage_percent: float | None = None,
        codebase_memory: dict[str, Any] | None = None,
        required_agent_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.acceptance_dir.mkdir(parents=True, exist_ok=True)
        gates = self.runtime.list_gate_states(run_id)
        results = self.runtime.list_agent_results(run_id)
        risks: list[str] = []
        provider_summary = self._provider_summary(results)
        gate_summary = {gate["gateName"]: gate["status"] for gate in gates}
        coverage = self._evaluate_coverage(coverage_percent, risks)
        codebase = self._evaluate_codebase_memory(codebase_memory or {}, risks)
        required_agent_ids = required_agent_ids or [agent.agent_id for agent in AgentRegistry.default().list_agents()]
        self._evaluate_required_node_terminality(run_id, set(required_agent_ids), risks)
        if any(result["synthetic"] for result in results):
            risks.append("synthetic_dependency_present")
        if any(result["providerFallbackTriggered"] for result in results):
            risks.append("provider_fallback_present")
        required_results = [result for result in results if result["agentId"] in required_agent_ids]
        result_agent_ids = {result["agentId"] for result in results}
        failure_agent_ids = self._failure_agent_ids(run_id)
        for agent_id in required_agent_ids:
            if agent_id not in result_agent_ids and agent_id not in failure_agent_ids:
                risks.append(f"agent_record_missing:{agent_id}")
        if required_results and any(result["providerUsed"] != "claude_cli" for result in required_results):
            risks.append("required_provider_not_claude_cli")
        if required_results and any(result["providerType"] != "real_llm" for result in required_results):
            risks.append("required_provider_not_real_llm")
        if required_results and any(not result["providerIdentityVerified"] for result in required_results):
            risks.append("provider_identity_not_verified")
        if not required_results:
            risks.append("required_results_missing")
        for gate_name in ["test_gate", "code_review_gate", "reality_checker_gate", "release_gate"]:
            if gate_summary.get(gate_name) != "pass":
                risks.append(f"{gate_name}_not_pass")
        pass_count = sum(1 for result in results if result["status"] == "pass")
        pass_rate = pass_count / len(results) if results else 0.0
        conclusion = "PASS" if not risks else "FAIL"
        payload = {
            "run_id": run_id,
            "conclusion": conclusion,
            "pass_rate": pass_rate,
            "gate_states": gate_summary,
            "provider_summary": provider_summary,
            "coverage": coverage,
            "coverage_baseline_created": coverage["baseline_created"],
            "codebase_memory": codebase,
            "risks": sorted(set(risks)),
        }
        output_path.write_text(self._render_markdown(payload), encoding="utf-8")
        return payload


    def _failure_agent_ids(self, run_id: str) -> set[str]:
        agent_ids: set[str] = set()
        for event in self.runtime.events.query(run_id, limit=100000).events:
            if event.type in {"provider_blocked", "agent_timeout", "invalid_agent_result", "tool_permission_denied", "checkpoint_mismatch", "dependency_blocked"}:
                agent_id = event.payload.get("agentId")
                if agent_id:
                    agent_ids.add(agent_id)
        return agent_ids

    def _evaluate_coverage(self, coverage_percent: float | None, risks: list[str]) -> dict[str, Any]:
        if coverage_percent is None:
            risks.append("coverage_blocked_by_environment")
            return {"status": "blocked_by_environment", "baseline_created": False, "total_percent": None, "baseline_percent": None}
        baseline_created = False
        if not self.baseline_path.exists():
            self.baseline_path.write_text(json.dumps({"total_percent": coverage_percent}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            baseline_created = True
            baseline = coverage_percent
            risks.append("coverage_baseline_created_requires_rerun")
        else:
            baseline = float(json.loads(self.baseline_path.read_text(encoding="utf-8"))["total_percent"])
        if coverage_percent < baseline:
            risks.append("coverage_below_baseline")
        return {"status": "ok", "baseline_created": baseline_created, "total_percent": coverage_percent, "baseline_percent": baseline}

    def _evaluate_codebase_memory(self, codebase_memory: dict[str, Any], risks: list[str]) -> dict[str, Any]:
        status = codebase_memory.get("status")
        architecture = codebase_memory.get("architecture")
        if status != "indexed":
            risks.append("codebase_memory_not_indexed")
        if not architecture:
            risks.append("codebase_architecture_empty")
        return {
            "status": status,
            "project": codebase_memory.get("project"),
            "nodes": codebase_memory.get("nodes"),
            "edges": codebase_memory.get("edges"),
            "architecture": architecture,
        }

    def _evaluate_required_node_terminality(self, run_id: str, required_agent_ids: set[str], risks: list[str]) -> None:
        for node in self.runtime.list_nodes(run_id):
            if node.owner_agent_id in required_agent_ids and node.status.value not in TERMINAL_NODE_STATUSES:
                risks.append(f"required_node_not_terminal:{node.owner_agent_id}")

    def _provider_summary(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "agentId": result["agentId"],
                "providerUsed": result["providerUsed"],
                "providerType": result["providerType"],
                "providerIdentityVerified": result["providerIdentityVerified"],
                "providerFallbackTriggered": result["providerFallbackTriggered"],
                "synthetic": result["synthetic"],
            }
            for result in results
        ]

    def _render_markdown(self, payload: dict[str, Any]) -> str:
        return "\n".join(
            [
                "# Squad Runtime Acceptance Report",
                "",
                f"Conclusion: {payload['conclusion']}",
                "",
                "```json",
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                "```",
                "",
            ]
        )
