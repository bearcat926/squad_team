from __future__ import annotations

from .models import GateDecision, TaskNode
from .runtime import Runtime
from .state import NodeStatus


class GateEngine:
    def __init__(self, runtime: Runtime):
        self.runtime = runtime

    def evaluate_all(self, run_id: str, trigger: str = "manual") -> dict[str, GateDecision]:
        decisions: dict[str, GateDecision] = {}
        decisions["test_gate"] = self.evaluate_test_gate(run_id)
        decisions["code_review_gate"] = self.evaluate_code_review_gate(run_id)
        decisions["reality_checker_gate"] = self.evaluate_reality_gate(run_id, decisions)
        decisions["release_gate"] = self.evaluate_release_gate(run_id, decisions)
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
                    "gateName": decision.gate_name,
                    "status": decision.status,
                    "reason": decision.reason,
                    "blockedReasonCode": decision.blocked_reason_code,
                    "trigger": trigger,
                    "details": decision.details or {},
                },
                critical=True,
            )
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

    def _facts_for(self, run_id: str, agent_id: str) -> list[dict]:
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
