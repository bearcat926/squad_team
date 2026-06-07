from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .models import GateDecision, TaskNode
from .runtime import Runtime
from .state import NodeStatus


@dataclass(frozen=True)
class GateEvidenceContext:
    schema_version: str
    mode: str
    artifacts: list[dict[str, Any]]
    verification_results: list[dict[str, Any]]
    agent_results: list[dict[str, Any]]


class GateEngine:
    def __init__(self, runtime: Runtime):
        self.runtime = runtime

    def evaluate_all(self, run_id: str, trigger: str = "manual", mode: Literal["legacy", "strict"] = "legacy") -> dict[str, GateDecision]:
        decisions = self._evaluate_strict(run_id) if mode == "strict" else self._evaluate_legacy(run_id)
        for decision in decisions.values():
            self.runtime.upsert_gate_state(
                run_id,
                decision.gate_name,
                decision.status,
                decision.reason,
                decision.blocked_reason_code,
            )
            self.runtime.events.append(
                run_id,
                "gate_decision",
                {
                    "schemaVersion": "gate-decision/v1",
                    "gateName": decision.gate_name,
                    "status": decision.status,
                    "reason": decision.reason,
                    "blockedReasonCode": decision.blocked_reason_code,
                    "trigger": trigger,
                    "mode": mode,
                    "details": decision.details or {},
                },
                critical=True,
            )
        return decisions

    def _evaluate_legacy(self, run_id: str) -> dict[str, GateDecision]:
        decisions: dict[str, GateDecision] = {}
        decisions["test_gate"] = self.evaluate_test_gate(run_id)
        decisions["code_review_gate"] = self.evaluate_code_review_gate(run_id)
        decisions["reality_checker_gate"] = self.evaluate_reality_gate(run_id, decisions)
        decisions["release_gate"] = self.evaluate_release_gate(run_id, decisions)
        return decisions

    def _evaluate_strict(self, run_id: str) -> dict[str, GateDecision]:
        context = self._gate_evidence_context(run_id)
        decisions: dict[str, GateDecision] = {}
        decisions["test_gate"] = self._evaluate_strict_test_gate(context)
        decisions["code_review_gate"] = self._evaluate_strict_code_review_gate(context)
        decisions["provider_authenticity_gate"] = self._evaluate_provider_authenticity_gate(context)
        decisions["evidence_authenticity_gate"] = self._evaluate_evidence_authenticity_gate(context)
        decisions["coverage_gate"] = self._evaluate_coverage_gate(context)
        decisions["chain_completeness_gate"] = self._evaluate_chain_completeness_gate(run_id)
        decisions["boundary_gate"] = self._evaluate_boundary_gate(context)
        decisions["reality_checker_gate"] = self.evaluate_reality_gate(run_id, decisions)
        decisions["release_gate"] = self._evaluate_strict_release_gate(context, decisions)
        return decisions

    def evaluate_test_gate(self, run_id: str) -> GateDecision:
        facts = self._facts_for(run_id, "test-engineer")
        if facts:
            failing = [fact for fact in facts if fact["status"] != "pass"]
            if failing:
                return GateDecision(
                    "test_gate",
                    "fail" if any(fact["status"] == "fail" for fact in failing) else "blocked",
                    "Test Engineer facts are not all passing",
                    blocked_reason_code="missing_test_pass",
                    details={"agentResults": [fact["id"] for fact in failing]},
                )
            return GateDecision("test_gate", "pass", "Test Engineer evidence passed", details={"agentResults": [fact["id"] for fact in facts]})
        return self._evaluate_test_gate_from_nodes(run_id)

    def evaluate_code_review_gate(self, run_id: str) -> GateDecision:
        facts = self._facts_for(run_id, "code-reviewer")
        if facts:
            blocking = [fact for fact in facts if fact["status"] in {"fail", "blocked"}]
            if blocking:
                return GateDecision(
                    "code_review_gate",
                    "fail",
                    "Blocking review result exists",
                    blocked_reason_code="missing_review_pass",
                    details={"agentResults": [fact["id"] for fact in blocking]},
                )
            approvals = [fact for fact in facts if fact["status"] == "pass"]
            if approvals:
                return GateDecision("code_review_gate", "pass", "Code Reviewer approved", details={"agentResults": [fact["id"] for fact in approvals]})
            return GateDecision("code_review_gate", "blocked", "No review approval", blocked_reason_code="missing_review_pass")
        return self._evaluate_code_review_gate_from_nodes(run_id)

    def evaluate_reality_gate(self, run_id: str, decisions: dict[str, GateDecision]) -> GateDecision:
        if decisions["test_gate"].status != "pass":
            return GateDecision(
                "reality_checker_gate",
                "blocked",
                "Test Gate not passed",
                blocked_reason_code="missing_test_pass",
            )
        facts = self._facts_for(run_id, "reality-checker")
        if facts:
            passed = [fact for fact in facts if fact["status"] == "pass"]
            if passed:
                return GateDecision("reality_checker_gate", "pass", "Reality Checker passed", details={"agentResults": [fact["id"] for fact in passed]})
            return GateDecision("reality_checker_gate", "blocked", "Reality Checker readiness result missing", blocked_reason_code="gate_dependency_failed")
        return self._evaluate_reality_gate_from_nodes(run_id, decisions)

    def evaluate_release_gate(self, run_id: str, decisions: dict[str, GateDecision]) -> GateDecision:
        for gate_name, reason_code in [
            ("test_gate", "missing_test_pass"),
            ("code_review_gate", "missing_review_pass"),
            ("reality_checker_gate", "gate_dependency_failed"),
        ]:
            if decisions[gate_name].status != "pass":
                return GateDecision(
                    "release_gate",
                    "blocked",
                    f"{gate_name} not passed",
                    blocked_reason_code=reason_code,
                )
        return GateDecision("release_gate", "pass", "All prerequisite gates passed")

    def _facts_for(self, run_id: str, agent_id: str) -> list[dict[str, Any]]:
        return [result for result in self.runtime.list_agent_results(run_id) if result["agentId"] == agent_id and not result["synthetic"]]

    def _evaluate_test_gate_from_nodes(self, run_id: str) -> GateDecision:
        tests = self._active_nodes(run_id, "test")
        if not tests:
            return GateDecision("test_gate", "blocked", "No active test nodes", blocked_reason_code="missing_test_pass")
        failing = [node for node in tests if node.status != NodeStatus.PASS]
        if failing:
            return GateDecision(
                "test_gate",
                "fail" if any(node.status == NodeStatus.FAIL for node in failing) else "blocked",
                f"{len(failing)} active test node(s) not passing",
                blocked_reason_code="missing_test_pass",
                details={"nodes": [node.id for node in failing]},
            )
        return GateDecision("test_gate", "pass", "All active test nodes passed", details={"nodes": [node.id for node in tests]})

    def _evaluate_code_review_gate_from_nodes(self, run_id: str) -> GateDecision:
        reviews = self._active_nodes(run_id, "review")
        if not reviews:
            return GateDecision("code_review_gate", "blocked", "No active review nodes", blocked_reason_code="missing_review_pass")
        blocking = [node for node in reviews if node.status in {NodeStatus.FAIL, NodeStatus.BLOCKED}]
        if blocking:
            return GateDecision(
                "code_review_gate",
                "fail",
                "Blocking review findings exist",
                blocked_reason_code="missing_review_pass",
                details={"nodes": [node.id for node in blocking]},
            )
        approvals = [node for node in reviews if node.status == NodeStatus.PASS]
        if not approvals:
            return GateDecision("code_review_gate", "blocked", "No review approval", blocked_reason_code="missing_review_pass")
        return GateDecision("code_review_gate", "pass", "At least one review approved", details={"nodes": [node.id for node in approvals]})

    def _evaluate_reality_gate_from_nodes(self, run_id: str, decisions: dict[str, GateDecision]) -> GateDecision:
        reality_nodes = self._active_nodes(run_id, "gate")
        passed = [node for node in reality_nodes if node.owner_agent_id == "reality-checker" and node.status == NodeStatus.PASS]
        if not passed:
            return GateDecision(
                "reality_checker_gate",
                "blocked",
                "Reality Checker readiness result missing",
                blocked_reason_code="gate_dependency_failed",
            )
        return GateDecision("reality_checker_gate", "pass", "Reality Checker passed", details={"nodes": [node.id for node in passed]})

    def _active_nodes(self, run_id: str, node_type: str) -> list[TaskNode]:
        inactive = {NodeStatus.STALE, NodeStatus.CANCELED}
        return [node for node in self.runtime.list_nodes(run_id) if node.type == node_type and node.status not in inactive and not node.replaced_by_node_id]

    def _gate_evidence_context(self, run_id: str) -> GateEvidenceContext:
        events = self.runtime.events.query(run_id, limit=100000).events
        artifacts = [event.payload for event in events if event.type == "artifact_produced"]
        verification_results = [event.payload for event in events if event.type == "verification_result"]
        return GateEvidenceContext(
            schema_version="gate-evidence-context/v1",
            mode="strict",
            artifacts=artifacts,
            verification_results=verification_results,
            agent_results=self.runtime.list_agent_results(run_id),
        )

    def _evaluate_strict_test_gate(self, context: GateEvidenceContext) -> GateDecision:
        test_results = [result for result in context.agent_results if result["agentId"] == "test-engineer" and not result["synthetic"]]
        if not any(result["status"] == "pass" for result in test_results):
            return GateDecision("test_gate", "blocked", "Missing Test Engineer PASS fact", blocked_reason_code="missing_test_pass")
        if not any(artifact.get("type") == "test" for artifact in context.artifacts):
            return self._strict_fail("test_gate", "Missing test artifact", "EVIDENCE_MISSING")
        if not any(item.get("kind") == "ui_smoke" and item.get("status") == "pass" for item in context.verification_results):
            return self._strict_fail("test_gate", "Missing ui_smoke verification", "EVIDENCE_MISSING")
        return GateDecision("test_gate", "pass", "Strict test evidence passed", details={"schemaVersion": context.schema_version})

    def _evaluate_strict_code_review_gate(self, context: GateEvidenceContext) -> GateDecision:
        review_results = [result for result in context.agent_results if result["agentId"] == "code-reviewer" and not result["synthetic"]]
        if not any(result["status"] == "pass" for result in review_results):
            return GateDecision("code_review_gate", "blocked", "Missing Code Reviewer PASS fact", blocked_reason_code="missing_review_pass")
        if not any(artifact.get("type") in {"review", "review_fact", "review-artifact"} for artifact in context.artifacts):
            return self._strict_fail("code_review_gate", "Missing Review Fact artifact", "EVIDENCE_MISSING")
        return GateDecision("code_review_gate", "pass", "Strict review facts passed", details={"schemaVersion": context.schema_version})

    def _evaluate_provider_authenticity_gate(self, context: GateEvidenceContext) -> GateDecision:
        for result in context.agent_results:
            if (
                result["providerUsed"] != "claude_cli"
                or result["providerType"] != "real_llm"
                or not result["providerIdentityVerified"]
                or result["providerFallbackTriggered"]
                or result["synthetic"]
            ):
                return self._strict_fail("provider_authenticity_gate", "Provider authenticity failed", "PROVIDER_FAILURE")
        return GateDecision("provider_authenticity_gate", "pass", "Provider authenticity passed", details={"schemaVersion": context.schema_version})

    def _evaluate_evidence_authenticity_gate(self, context: GateEvidenceContext) -> GateDecision:
        for artifact in context.artifacts:
            if artifact.get("hashMatches") is False or artifact.get("snapshotHashMatches") is False:
                return self._strict_fail("evidence_authenticity_gate", "Artifact or snapshot hash mismatch", "EVIDENCE_TAMPERED")
        return GateDecision("evidence_authenticity_gate", "pass", "Evidence authenticity passed", details={"schemaVersion": context.schema_version})

    def _evaluate_coverage_gate(self, context: GateEvidenceContext) -> GateDecision:
        strengths = {"medium": 2, "high": 3}
        for item in context.verification_results:
            if item.get("kind") == "coverage" and item.get("status") == "pass" and strengths.get(str(item.get("evidenceStrength")), 0) >= 2:
                return GateDecision("coverage_gate", "pass", "Coverage evidence quality passed", details={"schemaVersion": context.schema_version})
        return self._strict_fail("coverage_gate", "Missing coverage extractor fact", "EVIDENCE_MISSING")

    def _evaluate_chain_completeness_gate(self, run_id: str) -> GateDecision:
        events = self.runtime.events.query(run_id, limit=100000).events
        has_event_hash = any(event.type == "event_hash_chain_sealed" and event.payload.get("finalEventHash") for event in events)
        has_chain_graph = any(event.type == "runtime_chain_graph_sealed" and event.payload.get("chainGraphHash") for event in events)
        if not has_event_hash or not has_chain_graph:
            return self._strict_fail("chain_completeness_gate", "Missing event hash chain or runtime chain graph", "EVIDENCE_MISSING")
        return GateDecision("chain_completeness_gate", "pass", "Chain completeness passed")

    def _evaluate_boundary_gate(self, context: GateEvidenceContext) -> GateDecision:
        for artifact in context.artifacts:
            path = str(artifact.get("path", ""))
            parts = path.replace("\\", "/").split("/")
            if path.startswith(("/", "\\")) or ".." in parts or ".squad" in parts:
                return self._strict_fail("boundary_gate", "Artifact path violates workspace boundary", "SECURITY_VIOLATION")
        return GateDecision("boundary_gate", "pass", "Boundary evidence passed", details={"schemaVersion": context.schema_version})

    def _evaluate_strict_release_gate(self, context: GateEvidenceContext, decisions: dict[str, GateDecision]) -> GateDecision:
        for gate_name, decision in decisions.items():
            if gate_name == "release_gate":
                continue
            if decision.status != "pass":
                return GateDecision(
                    "release_gate",
                    "blocked",
                    f"{gate_name} not passed",
                    blocked_reason_code=decision.blocked_reason_code or "gate_dependency_failed",
                    details={"blockingGate": gate_name, "failureClass": (decision.details or {}).get("failureClass")},
                )
        if not any(artifact.get("type") == "release_archive" for artifact in context.artifacts):
            return self._strict_fail("release_gate", "Missing release archive manifest", "EVIDENCE_MISSING")
        return GateDecision("release_gate", "pass", "Strict release evidence passed")

    @staticmethod
    def _strict_fail(gate_name: str, reason: str, failure_class: str) -> GateDecision:
        reason_code = {
            "EVIDENCE_MISSING": "evidence_missing",
            "EVIDENCE_TAMPERED": "evidence_tampered",
            "PROVIDER_FAILURE": "provider_failure",
            "SECURITY_VIOLATION": "security_violation",
        }.get(failure_class, "gate_dependency_failed")
        return GateDecision(
            gate_name,
            "fail",
            reason,
            blocked_reason_code=reason_code,
            details={"failureClass": failure_class},
        )
