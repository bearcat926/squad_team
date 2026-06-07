"""Scene C: Gate dependency chain verification with selective agent dispatch."""

import json
from pathlib import Path

from squad_runtime.adapter import AgentRuntimeAdapter
from squad_runtime.agent_registry import AgentRegistry
from squad_runtime.gate_engine import GateEngine
from squad_runtime.providers import ProviderRegistry
from squad_runtime.runtime import Runtime
from squad_runtime.state import NodeStatus


def run_gate_dependency_test(squad_dir: Path, scenario: str, agents_to_dispatch: list[str]):
    """Create all 10 nodes but only dispatch agents_to_dispatch."""
    runtime = Runtime.create(squad_dir)
    try:
        registry = AgentRegistry.default()
        providers = ProviderRegistry.default()
        adapter = AgentRuntimeAdapter(runtime, registry, providers)

        run = runtime.create_run(f"gate-deps-{scenario}")
        NODE_TYPES = {
            "squad-lead": "lead",
            "rapid-prototyper": "prototype",
            "software-architect": "architecture",
            "ui-designer": "design",
            "backend-architect": "backend",
            "frontend-developer": "frontend",
            "test-engineer": "test",
            "code-reviewer": "review",
            "reality-checker": "gate",
            "git-workflow-master": "release",
        }
        nodes = {}
        for agent_id in NODE_TYPES:
            nodes[agent_id] = runtime.create_node(run.id, f"{agent_id} task", NODE_TYPES[agent_id], agent_id)
            runtime.transition_node(nodes[agent_id].id, NodeStatus.TODO, NodeStatus.READY, "ready")

        for agent_id in agents_to_dispatch:
            adapter.dispatch_once(nodes[agent_id].id, provider_override="fake_cli")

        GateEngine(runtime).evaluate_all(run.id, trigger="gate_deps")
        gate_states = runtime.list_gate_states(run.id)
        return {"run_id": run.id, "gates": gate_states}
    finally:
        runtime.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Gate dependency chain test")
    parser.add_argument("--squad-dir", type=Path, default=Path.cwd() / ".squad")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/smoke-test-iteration-1"))
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    squad_dir = args.squad_dir.resolve()

    scenarios = [
        ("C-1", ["test-engineer"], {"test_gate": "pass", "code_review_gate": "blocked", "reality_checker_gate": "blocked", "release_gate": "blocked"}),
        (
            "C-2",
            ["test-engineer", "code-reviewer"],
            {"test_gate": "pass", "code_review_gate": "pass", "reality_checker_gate": "blocked", "release_gate": "blocked"},
        ),
        (
            "C-3",
            ["test-engineer", "reality-checker"],
            {"test_gate": "pass", "code_review_gate": "blocked", "reality_checker_gate": "pass", "release_gate": "blocked"},
        ),
        (
            "C-4",
            ["test-engineer", "code-reviewer", "reality-checker"],
            {"test_gate": "pass", "code_review_gate": "pass", "reality_checker_gate": "pass", "release_gate": "pass"},
        ),
    ]
    all_results = []
    all_pass = True
    for name, agents, expected in scenarios:
        result = run_gate_dependency_test(squad_dir, name, agents)
        gate_map = {g["gateName"]: g["status"] for g in result["gates"]}
        for gate_name, expected_status in expected.items():
            actual = gate_map.get(gate_name, "MISSING")
            if actual != expected_status:
                all_pass = False
                print(f"FAIL {name}: {gate_name} expected={expected_status} actual={actual}")
        result["scenario"] = name
        result["agents_to_dispatch"] = agents
        result["expected"] = expected
        result["actual"] = gate_map
        result["pass"] = all(gate_map.get(g, "MISSING") == s for g, s in expected.items())
        all_results.append(result)

    with open(output_dir / "gate-deps-results.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, default=str, indent=2)
    print(f"\n{'ALL PASS' if all_pass else 'FAILURES DETECTED'}")
    if not all_pass:
        raise SystemExit(1)
