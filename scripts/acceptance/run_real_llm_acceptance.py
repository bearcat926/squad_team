from __future__ import annotations

import argparse
import json
import sys
import threading
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from squad_runtime.acceptance import AcceptanceReporter
from squad_runtime.adapter import AgentRuntimeAdapter
from squad_runtime.agent_registry import AgentRegistry
from squad_runtime.gate_engine import GateEngine
from squad_runtime.providers import ProviderRegistry
from squad_runtime.runtime import Runtime
from squad_runtime.state import NodeStatus


class DispatchOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"
    CHECKPOINT_MISMATCH = "CHECKPOINT_MISMATCH"
    DEPENDENCY_BLOCKED = "DEPENDENCY_BLOCKED"


TERMINAL_STATUSES = {
    NodeStatus.PASS,
    NodeStatus.FAIL,
    NodeStatus.BLOCKED,
    NodeStatus.AGENT_UNAVAILABLE,
    NodeStatus.CANCELED,
    NodeStatus.STALE,
    NodeStatus.DONE,
}


NODE_TYPES = {
    "squad-lead": "lead",
    "rapid-prototyper": "prototype",
    "software-architect": "architecture",
    "ui-designer": "design",
    "backend-architect": "backend",
    "frontend-developer": "frontend",
    "backend-architect": "backend",
    "test-engineer": "test",
    "code-reviewer": "review",
    "reality-checker": "gate",
    "git-workflow-master": "release",
}


MINIMAL_ORDER = [
    "squad-lead",
    "frontend-developer",
    "test-engineer",
    "code-reviewer",
    "reality-checker",
]


FULL_TEAM_ORDER = [
    "squad-lead",
    "rapid-prototyper",
    "software-architect",
    "ui-designer",
    "backend-architect",
    "frontend-developer",
    "test-engineer",
    "code-reviewer",
    "reality-checker",
    "git-workflow-master",
]


@dataclass(frozen=True)
class ScenarioResult:
    run_id: str
    conclusion: str
    report_path: Path
    full_data_log_path: Path
    analysis_report_path: Path
    archive_path: Path
    dispatch_records: list[dict[str, Any]] = field(default_factory=list)
    report_payload: dict[str, Any] = field(default_factory=dict)


class ProviderDispatchLock:
    def __init__(self) -> None:
        self._semaphore = threading.Semaphore(1)

    def __enter__(self) -> None:
        self._semaphore.acquire()

    def __exit__(self, *_exc: object) -> None:
        self._semaphore.release()


class AcceptanceScenarioRunner:
    def __init__(
        self,
        runtime: Runtime,
        registry: AgentRegistry,
        providers: ProviderRegistry,
        provider_name: str,
        acceptance_root: Path,
        coverage_percent: float | None = None,
        codebase_memory: dict[str, Any] | None = None,
    ) -> None:
        self.runtime = runtime
        self.registry = registry
        self.providers = providers
        self.provider_name = provider_name
        self.acceptance_root = Path(acceptance_root)
        self.coverage_percent = coverage_percent
        self.codebase_memory = codebase_memory or {}
        self.dispatch_lock = ProviderDispatchLock()

    def run_minimal(self, implementation_agent_id: str = "frontend-developer") -> ScenarioResult:
        order = ["squad-lead", implementation_agent_id, "test-engineer", "code-reviewer", "reality-checker"]
        return self._run_scenario("minimal", order, require_preflight=False)

    def run_full_team(self) -> ScenarioResult:
        preflight = self.run_minimal()
        if preflight.conclusion != "PASS":
            raise RuntimeError(f"minimal preflight did not PASS: {preflight.conclusion}")
        return self._run_scenario("full-team", FULL_TEAM_ORDER, require_preflight=True)

    def _run_scenario(self, scenario: str, order: list[str], require_preflight: bool) -> ScenarioResult:
        run = self.runtime.create_run(f"{scenario} real LLM acceptance")
        checkpoint = f"ckp-{scenario}-{run.id}"
        nodes = {
            agent_id: self.runtime.create_node(run.id, self._title_for(agent_id, scenario), NODE_TYPES[agent_id], agent_id, checkpoint_id=checkpoint)
            for agent_id in order
        }
        self._record_scenario_start(run.id, scenario, order, require_preflight)
        self._record_acceptance_facts(run.id, scenario, order)
        self._record_required_coverage_lanes(run.id)
        records: list[dict[str, Any]] = []
        upstream_ok = True

        for agent_id in order:
            node = nodes[agent_id]
            if agent_id == "git-workflow-master":
                self._evaluate_gates(run.id)
                if self._gate_status(run.id, "release_gate") != "pass":
                    records.append(self._dependency_block(node, "release_gate_not_pass"))
                    upstream_ok = False
                    continue
            if not upstream_ok:
                records.append(self._dependency_block(node, "upstream_required_failed"))
                continue
            record = self._dispatch_node(node.id, agent_id)
            records.append(record)
            upstream_ok = record["outcome"] == DispatchOutcome.PASS.value
            self._evaluate_gates(run.id)

        self._evaluate_gates(run.id)
        return self._finalize(run.id, scenario, order, records)

    def _dispatch_node(self, node_id: str, agent_id: str) -> dict[str, Any]:
        node = self.runtime.get_node(node_id)
        self.runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "acceptance runner ready")
        with self.dispatch_lock:
            result = AgentRuntimeAdapter(self.runtime, self.registry, self.providers).dispatch_once(
                node.id,
                provider_override=self.provider_name,
            )
        updated = self.runtime.get_node(node.id)
        outcome = self._outcome_for(updated, result)
        return {
            "agentId": agent_id,
            "nodeId": node.id,
            "nodeStatus": updated.status.value,
            "blockedReasonCode": updated.blocked_reason_code,
            "outcome": outcome.value,
            "hasAgentResult": result is not None,
        }

    def _dependency_block(self, node, reason: str) -> dict[str, Any]:
        current = self.runtime.get_node(node.id)
        if current.status == NodeStatus.TODO:
            self.runtime.transition_node(
                node.id,
                NodeStatus.TODO,
                NodeStatus.BLOCKED,
                reason,
                blocked_reason_code="gate_dependency_failed",
            )
        self.runtime.events.append(
            node.run_id,
            "dependency_blocked",
            {"nodeId": node.id, "agentId": node.owner_agent_id, "reason": reason},
            critical=True,
        )
        return {
            "agentId": node.owner_agent_id,
            "nodeId": node.id,
            "nodeStatus": self.runtime.get_node(node.id).status.value,
            "blockedReasonCode": self.runtime.get_node(node.id).blocked_reason_code,
            "outcome": DispatchOutcome.DEPENDENCY_BLOCKED.value,
            "hasAgentResult": False,
        }

    def _outcome_for(self, node, result) -> DispatchOutcome:
        if result is not None:
            return DispatchOutcome(result.status.upper())
        if node.status == NodeStatus.AGENT_UNAVAILABLE:
            event_types = [event.type for event in self.runtime.events.query(node.run_id, limit=100000).events if event.payload.get("nodeId") == node.id]
            if "agent_timeout" in event_types:
                return DispatchOutcome.TIMEOUT
            return DispatchOutcome.UNAVAILABLE
        if node.status == NodeStatus.BLOCKED:
            if node.blocked_reason_code == "checkpoint_mismatch":
                return DispatchOutcome.CHECKPOINT_MISMATCH
            return DispatchOutcome.INVALID
        return DispatchOutcome.BLOCKED

    def _evaluate_gates(self, run_id: str) -> None:
        GateEngine(self.runtime).evaluate_all(run_id, trigger="acceptance_runner")

    def _gate_status(self, run_id: str, gate_name: str) -> str | None:
        for gate in self.runtime.list_gate_states(run_id):
            if gate["gateName"] == gate_name:
                return gate["status"]
        return None

    def _record_scenario_start(self, run_id: str, scenario: str, order: list[str], require_preflight: bool) -> None:
        self.runtime.record_event(
            run_id,
            "agent_operation",
            {"agentId": "squad-lead", "operation": "acceptance_scenario_started", "scenario": scenario, "order": order, "requirePreflight": require_preflight},
        )
        self.runtime.record_event(
            run_id,
            "skill_usage",
            {"agentId": "squad-lead", "skill": "using-superpowers", "usage": "acceptance discipline"},
        )

    def _record_required_coverage_lanes(self, run_id: str) -> None:
        for lane, owners in [
            ("Security Coverage Lane", ["backend-architect", "code-reviewer", "test-engineer"]),
            ("SRE Coverage Lane", ["backend-architect", "git-workflow-master", "reality-checker"]),
            ("Data Quality Lane", ["squad-lead", "backend-architect"]),
        ]:
            self.runtime.record_event(
                run_id,
                "coverage_lane_update",
                {"lane": lane, "status": "required", "owners": owners},
            )

    def _record_acceptance_facts(self, run_id: str, scenario: str, order: list[str]) -> None:
        self.runtime.record_event(
            run_id,
            "verification_result",
            {
                "scenario": scenario,
                "provider": self.provider_name,
                "acceptanceRoot": str(self.acceptance_root),
                "coveragePercent": self.coverage_percent,
                "codebaseMemory": self.codebase_memory,
                "sourceTree": {
                    "squadRuntimePackageExists": (self.acceptance_root / "squad_runtime").exists(),
                    "testsDirectoryExists": (self.acceptance_root / "tests").exists(),
                    "acceptanceRunnerExists": (self.acceptance_root / "scripts" / "acceptance" / "run_real_llm_acceptance.py").exists(),
                },
                "dispatchPolicy": {
                    "llmToolsEnabled": False,
                    "stateWriter": "Runtime only",
                    "outputContract": "AgentResult",
                    "providerTypeRequired": "real_llm",
                },
                "roleInstructions": {
                    "test-engineer": "Evaluate QA evidence from runtime facts, coverage, source tree facts, and dependency summaries. Do not require shell access in this isolated LLM dispatch.",
                    "code-reviewer": "Evaluate review readiness from runtime facts and dependency summaries. Do not require direct file reads in this isolated LLM dispatch.",
                    "reality-checker": "Evaluate release readiness from Test Gate, Code Review Gate, runtime facts, and dependency summaries.",
                    "git-workflow-master": "Only provide archive/release execution readiness after Release Gate pass.",
                },
                "requiredAgents": order,
            },
        )

    def _finalize(self, run_id: str, scenario: str, required_agent_ids: list[str], dispatch_records: list[dict[str, Any]]) -> ScenarioResult:
        report_path = self.acceptance_root / "acceptance-report.md"
        full_data_log_path = self.acceptance_root / "FULL_DATA_LOG.md"
        analysis_path = self.acceptance_root / "ANALYSIS_REPORT.zh-CN.md"
        self.runtime.export_run_log(run_id, full_data_log_path, include_export_event=True)
        analysis_path.write_text(self._render_analysis(run_id, scenario, dispatch_records), encoding="utf-8")
        archive_path = self.runtime.archive_run(run_id)
        payload = AcceptanceReporter(self.runtime).write_report(
            run_id,
            report_path,
            coverage_percent=self.coverage_percent,
            codebase_memory=self.codebase_memory,
            required_agent_ids=required_agent_ids,
        )
        return ScenarioResult(
            run_id=run_id,
            conclusion=payload["conclusion"],
            report_path=report_path,
            full_data_log_path=full_data_log_path,
            analysis_report_path=analysis_path,
            archive_path=archive_path,
            dispatch_records=dispatch_records,
            report_payload=payload,
        )

    def _render_analysis(self, run_id: str, scenario: str, dispatch_records: list[dict[str, Any]]) -> str:
        return "\n".join(
            [
                "# Squad Runtime Analysis Report zh-CN",
                "",
                f"Run: {run_id}",
                f"Scenario: {scenario}",
                "",
                "```json",
                json.dumps({"dispatchRecords": dispatch_records}, ensure_ascii=False, indent=2, sort_keys=True),
                "```",
                "",
            ]
        )

    def _title_for(self, agent_id: str, scenario: str) -> str:
        role_tasks = {
            "squad-lead": "confirm product and orchestration acceptance from provided runtime facts",
            "rapid-prototyper": "confirm prototype validation readiness from provided runtime facts",
            "software-architect": "confirm architecture acceptance from dependency summaries and runtime facts",
            "ui-designer": "confirm design and accessibility acceptance from dependency summaries and runtime facts",
            "backend-architect": "confirm backend/data/security coverage acceptance from dependency summaries and runtime facts",
            "frontend-developer": "confirm frontend implementation readiness from dependency summaries and runtime facts",
            "test-engineer": "confirm QA evidence from coverage, source tree facts, and dependency summaries without tool access",
            "code-reviewer": "confirm code review readiness from runtime facts and dependency summaries without direct file reads",
            "reality-checker": "confirm release readiness from gate facts, QA evidence, review evidence, and dependency summaries",
            "git-workflow-master": "confirm release archive execution after Release Gate pass",
        }
        return f"{scenario} acceptance task for {agent_id}: {role_tasks[agent_id]}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Squad Runtime real LLM acceptance scenarios.")
    parser.add_argument("--scenario", choices=["minimal", "full-team"], required=True)
    parser.add_argument("--provider", default="claude_cli")
    parser.add_argument("--acceptance-root", type=Path, required=True)
    parser.add_argument("--coverage-percent", type=float, default=None)
    parser.add_argument("--codebase-memory-status", default=None)
    parser.add_argument("--codebase-memory-project", default=None)
    parser.add_argument("--codebase-memory-nodes", type=int, default=None)
    parser.add_argument("--codebase-memory-edges", type=int, default=None)
    parser.add_argument("--architecture-status", default=None)
    args = parser.parse_args()

    acceptance_root = args.acceptance_root.resolve()
    runtime = Runtime.create(acceptance_root / ".squad")
    runner = AcceptanceScenarioRunner(
        runtime=runtime,
        registry=AgentRegistry.default(),
        providers=ProviderRegistry.default(),
        provider_name=args.provider,
        acceptance_root=acceptance_root,
        coverage_percent=args.coverage_percent,
        codebase_memory={
            "status": args.codebase_memory_status,
            "project": args.codebase_memory_project,
            "nodes": args.codebase_memory_nodes,
            "edges": args.codebase_memory_edges,
            "architecture": args.architecture_status,
        },
    )
    result = runner.run_minimal() if args.scenario == "minimal" else runner.run_full_team()
    print(json.dumps({"runId": result.run_id, "conclusion": result.conclusion, "reportPath": str(result.report_path)}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
