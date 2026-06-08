from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agent_registry import AgentRegistry
from .evidence_policy import EvidencePolicy
from .profile_registry import EvidenceScenarioType, ResolvedProfileLoader
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
        scenario_type: str = "smoke",
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
        frozen_profile = ResolvedProfileLoader.default().freeze(EvidenceScenarioType(scenario_type))
        evidence_gate = EvidencePolicy(frozen_profile).evaluate(self._collect_runtime_facts(run_id, results))
        if evidence_gate.status != "pass":
            risks.append("evidence_gate_failed")
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
        self._evaluate_tool_and_provider_risks(run_id, risks)
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
            "evidence_gate": evidence_gate.to_dict(),
            "resolved_profile_hash": frozen_profile.resolved_profile_hash,
            "source_profiles": list(frozen_profile.source_profiles),
            "failure_classification_summary": self._failure_classification_summary(evidence_gate.to_dict()),
            "risks": sorted(set(risks)),
        }
        output_path.write_text(self._render_markdown(payload), encoding="utf-8")
        return payload

    def _failure_agent_ids(self, run_id: str) -> set[str]:
        agent_ids: set[str] = set()
        for event in self.runtime.events.query(run_id, limit=100000).events:
            if event.type in {
                "provider_blocked",
                "provider_rate_limited",
                "agent_timeout",
                "invalid_agent_result",
                "tool_permission_denied",
                "checkpoint_mismatch",
                "dependency_blocked",
                "illegal_tool_requested",
                "tool_loop_timeout",
                "tool_loop_max_rounds_exceeded",
                "boundary_violation",
                "command_not_declared",
                "silent_provider_fallback",
                "provider_error",
            }:
                agent_id = event.payload.get("agentId")
                if agent_id:
                    agent_ids.add(agent_id)
        return agent_ids

    def _evaluate_tool_and_provider_risks(self, run_id: str, risks: list[str]) -> None:
        """Detect tool loop and provider error events and add corresponding risks."""
        tool_risk_event_types = {
            "tool_loop_timeout": "tool_loop_timeout",
            "tool_loop_max_rounds_exceeded": "tool_loop_max_rounds_exceeded",
            "illegal_tool_requested": "illegal_tool_requested",
            "boundary_violation": "boundary_violation",
            "command_not_declared": "command_not_declared",
            "silent_provider_fallback": "silent_provider_fallback",
            "provider_error": "provider_error",
            "tool_permission_denied": "tool_permission_denied",
            "provider_blocked": "provider_blocked",
            "provider_rate_limited": "provider_rate_limited",
            "agent_timeout": "agent_timeout",
            "invalid_agent_result": "invalid_agent_result",
            "checkpoint_mismatch": "checkpoint_mismatch",
            "dependency_blocked": "dependency_blocked",
        }
        for event in self.runtime.events.query(run_id, limit=100000).events:
            risk_code = tool_risk_event_types.get(event.type)
            if risk_code and risk_code not in risks:
                risks.append(risk_code)

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

    def _collect_runtime_facts(self, run_id: str, results: list[dict[str, Any]]) -> dict[str, Any]:
        events = self.runtime.events.query(run_id, limit=100000).events
        return {
            "agentResults": results,
            "evidenceItems": self.runtime.list_evidence_items(run_id),
            "artifacts": self._artifacts_with_existence(self.runtime.list_artifacts(run_id)),
            "reviewFindings": self.runtime.list_review_findings(run_id),
            "reviewArtifacts": [
                event.payload
                for event in events
                if event.type == "artifact_produced" and event.payload.get("type") in {"review", "review_fact", "review-artifact"}
            ],
            "verificationResults": [event.payload for event in events if event.type == "verification_result"],
            "coverageLanes": [event.payload for event in events if event.type == "coverage_lane_update"],
            "skillUsage": [event.payload for event in events if event.type == "skill_usage"],
            "eventHashChain": self._event_hash_chain_fact(events),
        }

    def _artifacts_with_existence(self, artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for artifact in artifacts:
            item = dict(artifact)
            path = Path(str(item.get("path", "")))
            if path.is_absolute():
                item["exists"] = path.exists()
            else:
                item["exists"] = (self.runtime.squad_dir.parent / path).exists() or (self.runtime.squad_dir / "artifacts" / path).exists()
            enriched.append(item)
        return enriched

    @staticmethod
    def _event_hash_chain_fact(events: list[Any]) -> dict[str, Any]:
        final_hash = None
        for event in events:
            if event.type == "event_hash_chain_sealed":
                final_hash = event.payload.get("finalEventHash")
        return {"status": "present", "finalEventHash": final_hash} if final_hash else {"status": "missing"}

    @staticmethod
    def _failure_classification_summary(evidence_gate: dict[str, Any]) -> dict[str, int]:
        summary: dict[str, int] = {}
        for group in ["missing", "invalid", "tampered", "warnings"]:
            for item in evidence_gate[group]:
                failure_class = item["failureClass"]
                summary[failure_class] = summary.get(failure_class, 0) + 1
        return summary

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
