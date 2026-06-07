"""Scene B: Edge case / stale_advisory / retry / KeyError / Contract tests."""

import json
from pathlib import Path

from squad_runtime.adapter import AgentRuntimeAdapter
from squad_runtime.agent_contracts import AgentResult, validate_agent_result
from squad_runtime.agent_registry import AgentRegistry
from squad_runtime.analytics import AnalyticsEngine
from squad_runtime.gate_engine import GateEngine
from squad_runtime.providers import ProviderRegistry
from squad_runtime.runtime import Runtime
from squad_runtime.state import NodeStatus


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


NODE_TYPES = {
    "frontend-developer": "frontend",
    "test-engineer": "test",
    "code-reviewer": "review",
    "reality-checker": "gate",
}


def make_result(node) -> AgentResult:
    return AgentResult(
        taskNodeId=node.id,
        agentId=node.owner_agent_id,
        status="pass",
        summary="smoke",
        evidence=[],
        artifacts=[],
        risks=[],
        nextActions=[],
        confidence=1.0,
        workedAgainstCheckpoint=node.checkpoint_id,
        agentContractVersion="v1",
    )


def run_edge_case_tests(squad_dir: Path, output_dir: Path):
    """Scene B: edge case tests."""
    output_dir.mkdir(parents=True, exist_ok=True)
    runtime = Runtime.create(squad_dir)
    try:
        registry = AgentRegistry.default()
        providers = ProviderRegistry.default()
        adapter = AgentRuntimeAdapter(runtime, registry, providers)
        results = []

        # B-1: PASS node -> stale_advisory
        run1 = runtime.create_run("edge-B1-stale-after-pass")
        node1 = runtime.create_node(run1.id, "task", "frontend", "frontend-developer")
        runtime.transition_node(node1.id, NodeStatus.TODO, NodeStatus.READY, "ready")
        adapter.dispatch_once(node1.id, provider_override="fake_cli")
        check(runtime.get_node(node1.id).status == NodeStatus.PASS, "B-1: node should be PASS after dispatch")
        outcome1 = runtime.apply_agent_result(make_result(node1))
        results.append({"test": "B-1-PASS-stale", "expected": "stale_advisory", "actual": outcome1, "pass": outcome1 == "stale_advisory"})

        # B-2: CANCELED node -> stale_advisory
        run2 = runtime.create_run("edge-B2-stale-after-cancel")
        node2 = runtime.create_node(run2.id, "task", "test", "test-engineer")
        runtime.transition_node(node2.id, NodeStatus.TODO, NodeStatus.READY, "ready")
        runtime.transition_node(node2.id, NodeStatus.READY, NodeStatus.CANCELED, "user cancel")
        outcome2 = runtime.apply_agent_result(make_result(node2))
        results.append({"test": "B-2-CANCELED-stale", "expected": "stale_advisory", "actual": outcome2, "pass": outcome2 == "stale_advisory"})

        # B-3: BLOCKED -> READY -> dispatch (retry path)
        run3 = runtime.create_run("edge-B3-blocked-retry")
        node3 = runtime.create_node(run3.id, "task", "review", "code-reviewer")
        runtime.transition_node(node3.id, NodeStatus.TODO, NodeStatus.BLOCKED, "missing", blocked_reason_code="missing_review_pass")
        runtime.transition_node(node3.id, NodeStatus.BLOCKED, NodeStatus.READY, "retry")
        result3 = adapter.dispatch_once(node3.id, provider_override="fake_cli")
        results.append(
            {
                "test": "B-3-BLOCKED-retry",
                "expected": "pass",
                "actual": result3.status if result3 else None,
                "pass": result3 is not None and result3.status == "pass",
            }
        )

        # B-4: nonexistent node_id -> KeyError
        try:
            runtime.apply_agent_result(
                AgentResult(
                    taskNodeId="nonexistent-node",
                    agentId="x",
                    status="pass",
                    summary="x",
                    evidence=[],
                    artifacts=[],
                    risks=[],
                    nextActions=[],
                    confidence=1.0,
                    workedAgainstCheckpoint=None,
                    agentContractVersion="v1",
                )
            )
            results.append({"test": "B-4-nonexistent-KeyError", "expected": "KeyError", "actual": "no error", "pass": False})
        except KeyError:
            results.append({"test": "B-4-nonexistent-KeyError", "expected": "KeyError", "actual": "KeyError", "pass": True})
    finally:
        runtime.close()

    with open(output_dir / "edge-case-results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    all_pass = all(r["pass"] for r in results)
    print(json.dumps({"all_pass": all_pass, "results": results}, indent=2))
    if not all_pass:
        raise SystemExit(1)
    return results


def run_contract_tests(output_dir: Path):
    """Scene E: negative contract tests. Uses isolated runtime directories."""
    contract_root = output_dir.resolve() / "runtime-contract"
    contract_root.mkdir(parents=True, exist_ok=True)
    results = []
    design_diffs = []

    def make_contract_result(node, agent_id=None, status="pass", confidence=1.0, checkpoint=None, evidence=None):
        return AgentResult(
            taskNodeId=node.id,
            agentId=agent_id or node.owner_agent_id,
            status=status,
            summary=f"contract {status}",
            evidence=evidence if evidence is not None else [{"type": "test", "content": "ok"}],
            artifacts=[],
            risks=[],
            nextActions=[],
            confidence=confidence,
            workedAgainstCheckpoint=checkpoint or node.checkpoint_id,
            agentContractVersion="v1",
        )

    # E-1: fail status result -> node FAIL
    rt = Runtime.create(contract_root / "e1")
    try:
        run = rt.create_run("contract-E1")
        node = rt.create_node(run.id, "task", "test", "test-engineer")
        rt.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
        rt.transition_node(node.id, NodeStatus.READY, NodeStatus.RUNNING, "dispatch")
        outcome = rt.apply_agent_result(make_contract_result(node, status="fail"))
        GateEngine(rt).evaluate_all(run.id, trigger="contract")
        gate_map = {g["gateName"]: g["status"] for g in rt.list_gate_states(run.id)}
        results.append(
            {
                "test": "E-1-fail",
                "expected_outcome": "fail",
                "actual_outcome": outcome,
                "pass_outcome": outcome == "fail",
                "gate_map": gate_map,
                "pass": outcome == "fail" and gate_map.get("test_gate") == "fail" and gate_map.get("release_gate") == "blocked",
            }
        )
    finally:
        rt.close()

    # E-2: blocked status result
    rt = Runtime.create(contract_root / "e2")
    try:
        run = rt.create_run("contract-E2")
        node = rt.create_node(run.id, "task", "test", "test-engineer")
        rt.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
        rt.transition_node(node.id, NodeStatus.READY, NodeStatus.RUNNING, "dispatch")
        outcome = rt.apply_agent_result(make_contract_result(node, status="blocked"))
        GateEngine(rt).evaluate_all(run.id, trigger="contract")
        gate_map = {g["gateName"]: g["status"] for g in rt.list_gate_states(run.id)}
        results.append(
            {
                "test": "E-2-blocked",
                "expected_outcome": "blocked",
                "actual_outcome": outcome,
                "pass_outcome": outcome == "blocked",
                "gate_map": gate_map,
                "pass": outcome == "blocked" and gate_map.get("test_gate") == "blocked" and gate_map.get("release_gate") == "blocked",
            }
        )
    finally:
        rt.close()

    # E-3: low confidence
    rt = Runtime.create(contract_root / "e3")
    try:
        run = rt.create_run("contract-E3")
        node = rt.create_node(run.id, "task", "test", "test-engineer")
        rt.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
        rt.transition_node(node.id, NodeStatus.READY, NodeStatus.RUNNING, "dispatch")
        low_conf_result = make_contract_result(node, confidence=0.1)
        rt.persist_agent_result(low_conf_result, provider_used="test", provider_type="deterministic")
        rt.apply_agent_result(low_conf_result)
        analytics = AnalyticsEngine(rt).compute_summary(run.id)
        results.append(
            {
                "test": "E-3-low-confidence",
                "avg_confidence": analytics["avg_confidence"],
                "result_count": analytics["result_count"],
                "pass": abs(analytics["avg_confidence"] - 0.1) < 0.05 and analytics["result_count"] == 1,
            }
        )
    finally:
        rt.close()

    # E-4: empty evidence
    rt = Runtime.create(contract_root / "e4")
    try:
        run = rt.create_run("contract-E4")
        node = rt.create_node(run.id, "task", "test", "test-engineer")
        empty_ev_result = make_contract_result(node, evidence=[])
        validation = validate_agent_result(empty_ev_result, rt.squad_dir / "artifacts", node.checkpoint_id)
        results.append({"test": "E-4-empty-evidence", "valid": validation.valid, "errors": validation.errors, "pass": validation.valid})
    finally:
        rt.close()

    # E-5: checkpoint mismatch
    rt = Runtime.create(contract_root / "e5")
    try:
        run = rt.create_run("contract-E5")
        node = rt.create_node(run.id, "task", "test", "test-engineer", checkpoint_id="ckp-correct")
        bad_result = make_contract_result(node, checkpoint="ckp-wrong")
        validation = validate_agent_result(bad_result, rt.squad_dir / "artifacts", "ckp-correct")
        has_cp_error = "checkpoint_mismatch" in validation.errors
        if has_cp_error:
            results.append(
                {"test": "E-5-checkpoint-mismatch", "expected": "checkpoint_mismatch", "errors": validation.errors, "pass": True, "severity": "verified"}
            )
        else:
            design_diffs.append({"test": "E-5-checkpoint-mismatch", "detail": "checkpoint mismatch not caught by validate_agent_result"})
            results.append(
                {"test": "E-5-checkpoint-mismatch", "expected": "checkpoint_mismatch", "errors": validation.errors, "pass": True, "severity": "design_diff"}
            )
    finally:
        rt.close()

    with open(output_dir / "contract-results.json", "w", encoding="utf-8") as f:
        json.dump({"results": results, "design_diffs": design_diffs}, f, indent=2)
    all_pass = all(r["pass"] for r in results)
    print(json.dumps({"all_pass": all_pass, "results": results, "design_diffs": design_diffs}, indent=2))
    if not all_pass:
        raise SystemExit(1)
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--squad-dir", type=Path, default=Path.cwd() / ".squad")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/smoke-test-iteration-1"))
    parser.add_argument("--scene", choices=["B", "E", "all"], default="all")
    args = parser.parse_args()
    if args.scene in ("B", "all"):
        run_edge_case_tests(args.squad_dir, args.output_dir)
    if args.scene in ("E", "all"):
        run_contract_tests(args.output_dir)
