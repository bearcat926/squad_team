"""Full-team smoke dispatch with configurable provider."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from squad_runtime.adapter import AgentRuntimeAdapter
from squad_runtime.agent_registry import AgentRegistry
from squad_runtime.analytics import AnalyticsEngine
from squad_runtime.gate_engine import GateEngine
from squad_runtime.providers import ProviderRegistry
from squad_runtime.runtime import Runtime
from squad_runtime.scheduler import Scheduler
from squad_runtime.state import NodeStatus

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


def check(condition: bool, message: str) -> None:
    """Assertions that survive python -O."""
    if not condition:
        raise AssertionError(message)


def run_scenario(squad_dir: Path, scenario_name: str, provider: str = "fake_cli", output_dir: Path | None = None):
    runtime = Runtime.create(squad_dir)
    try:
        registry = AgentRegistry.default()
        providers = ProviderRegistry.default()
        adapter = AgentRuntimeAdapter(runtime, registry, providers)

        run = runtime.create_run(f"{scenario_name} smoke test")

        nodes = {}
        for agent_id in FULL_TEAM_ORDER:
            nodes[agent_id] = runtime.create_node(run.id, f"{agent_id} task", NODE_TYPES[agent_id], agent_id)

        scheduler = Scheduler(runtime, global_limit=4, per_agent_type_limit=1)
        check(not scheduler.select_dispatch_candidates(run.id), "Scheduler should return empty when all nodes are TODO")
        results = []
        for agent_id in FULL_TEAM_ORDER:
            node = nodes[agent_id]
            runtime.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "smoke ready")
            candidates = scheduler.select_dispatch_candidates(run.id)
            check(any(c.id == node.id for c in candidates), f"Scheduler should include {agent_id} node")
            result, rate_limit_retries = dispatch_with_rate_limit_retry(runtime, providers, adapter, node.id, agent_id, provider)
            GateEngine(runtime).evaluate_all(run.id, trigger="smoke")
            results.append(
                {
                    "agentId": agent_id,
                    "nodeId": node.id,
                    "status": runtime.get_node(node.id).status.value,
                    "result": result.status if result else None,
                    "rateLimitRetries": rate_limit_retries,
                }
            )

        analytics = AnalyticsEngine(runtime).compute_summary(run.id)
        gate_states = runtime.list_gate_states(run.id)

        export_path = output_dir / f"FULL_DATA_LOG-{scenario_name}.json" if output_dir else squad_dir.parent / f"FULL_DATA_LOG_{scenario_name}.json"
        runtime.export_run_log(run.id, export_path)
        archive_path = runtime.archive_run(run.id)
        return {
            "run_id": run.id,
            "results": results,
            "analytics": analytics,
            "gate_states": gate_states,
            "export_path": str(export_path),
            "archive_path": str(archive_path),
        }
    finally:
        runtime.close()


def dispatch_with_rate_limit_retry(
    runtime: Runtime, providers: ProviderRegistry, adapter: AgentRuntimeAdapter, node_id: str, agent_id: str, provider_name: str
):
    retries = 0
    retry_limit = rate_limit_retry_limit(providers, provider_name)
    result = None
    while True:
        before_count = provider_rate_limited_count(runtime, node_id)
        result = adapter.dispatch_once(node_id, provider_override=provider_name)
        updated = runtime.get_node(node_id)
        after_count = provider_rate_limited_count(runtime, node_id)
        if updated.status != NodeStatus.AGENT_UNAVAILABLE or after_count <= before_count or retries >= retry_limit:
            return result, retries
        retries += 1
        runtime.events.append(
            updated.run_id,
            "provider_rate_limit_retry",
            {"nodeId": node_id, "agentId": agent_id, "provider": provider_name, "attempt": retries, "maxRetries": retry_limit},
            critical=True,
        )
        runtime.transition_node(node_id, NodeStatus.AGENT_UNAVAILABLE, NodeStatus.READY, "provider rate limit retry")


def provider_rate_limited_count(runtime: Runtime, node_id: str) -> int:
    node = runtime.get_node(node_id)
    return sum(
        1
        for event in runtime.events.query(node.run_id, limit=100000).events
        if event.type == "provider_rate_limited" and event.payload.get("nodeId") == node_id
    )


def rate_limit_retry_limit(providers: ProviderRegistry, provider_name: str) -> int:
    provider = providers.get(provider_name)
    if hasattr(provider, "rate_limit_retry_limit"):
        return int(provider.rate_limit_retry_limit())
    try:
        return max(int(os.environ.get("SQUAD_CLAUDE_CLI_RATE_LIMIT_RETRIES", "1")), 0)
    except ValueError:
        return 1


def write_scene_f_status(
    output_dir: Path,
    scenario_name: str,
    status: str,
    reason: str,
    run_id: str | None = None,
    provider: str = "claude_cli",
    extra: dict | None = None,
    overwrite: bool = False,
) -> None:
    status_path = output_dir / f"scene-F-status-{scenario_name}.json"
    if status_path.exists() and not overwrite and status == "fail":
        return
    payload: dict = {"scene": "F", "scenario": scenario_name, "status": status, "reason": reason, "provider": provider}
    if run_id:
        payload["run_id"] = run_id
    if extra:
        payload.update(extra)
    status_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_scene_f_summary(output_dir: Path, all_scenario_names: list[str]) -> None:
    summary = {"scene": "F", "rounds": len(all_scenario_names), "scenarios": {}}
    for name in all_scenario_names:
        sp = output_dir / f"scene-F-status-{name}.json"
        if sp.exists():
            summary["scenarios"][name] = json.loads(sp.read_text(encoding="utf-8"))
    (output_dir / "scene-F-status.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


def make_status_context(cm_raw_status: str, cm_normalized: str, coverage_percent: float | None, extra: dict | None = None) -> dict:
    ctx = {
        "raw_codebase_memory_status": cm_raw_status,
        "normalized_codebase_memory_status": cm_normalized,
        "coverage_percent": coverage_percent,
    }
    if extra:
        ctx.update(extra)
    return ctx


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Full-team smoke dispatch")
    parser.add_argument("--squad-dir", type=Path, default=Path.cwd() / ".squad")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/smoke-test-iteration-1"))
    parser.add_argument("--scenario", default="scene-A")
    parser.add_argument("--provider", choices=["fake_cli", "claude_cli"], default="fake_cli")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--coverage-percent", type=float, default=None)
    parser.add_argument("--codebase-memory-status", default=None)
    parser.add_argument("--codebase-memory-project", default=None)
    parser.add_argument("--codebase-memory-nodes", type=int, default=None)
    parser.add_argument("--codebase-memory-edges", type=int, default=None)
    parser.add_argument("--architecture-status", default=None)
    args = parser.parse_args()

    squad_dir_resolved = args.squad_dir.resolve()
    if args.provider == "claude_cli" and squad_dir_resolved.name != ".squad":
        print(f"ERROR: --squad-dir must end with /.squad for claude_cli, got {squad_dir_resolved}", file=sys.stderr)
        raise SystemExit(1)
    repo_root = squad_dir_resolved.parent
    env = os.environ.copy()
    env["SQUAD_ACCEPTANCE_ROOT"] = str(repo_root)

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    def normalize_cm_status(raw: str | None) -> tuple[str, str]:
        if raw is None:
            return ("missing", "missing")
        if raw.lower() in ("indexed", "ready", "ok"):
            return (raw, "indexed")
        return (raw, "fail")

    cm_raw_status, cm_normalized = normalize_cm_status(args.codebase_memory_status)

    def parse_acceptance_risks(stdout: str, report_md: str) -> dict:
        try:
            payload = json.loads(stdout)
            risks = payload.get("risks")
            if not isinstance(risks, list):
                return {"parsed": False, "conclusion": None, "risks": []}
            conclusion = payload.get("conclusion")
            return {"parsed": True, "conclusion": conclusion, "risks": risks}
        except (json.JSONDecodeError, TypeError):
            pass
        import re

        for m in re.finditer(r"```json\s*(.*?)\s*```", report_md, re.DOTALL):
            try:
                payload = json.loads(m.group(1))
                risks = payload.get("risks")
                if not isinstance(risks, list):
                    continue
                conclusion = payload.get("conclusion")
                return {"parsed": True, "conclusion": conclusion, "risks": risks}
            except (json.JSONDecodeError, TypeError):
                continue
        return {"parsed": False, "conclusion": None, "risks": []}

    def structured_risk_scan(
        scan_context: dict,
        report_text: str,
        acceptance_risks: list[str],
        export_payload: dict,
        archive_payload: dict,
        agent_results: list,
        stdout_stderr_text: str,
    ) -> list[str]:
        found = set()
        event_types = scan_context.get("event_types", set())
        type_risk_map: dict[str, str] = {
            "provider_blocked": "provider_blocked",
            "agent_timeout": "agent_timeout",
            "invalid_agent_result": "invalid_agent_result",
            "checkpoint_mismatch": "checkpoint_mismatch",
            "tool_permission_denied": "tool_permission_denied",
            "dependency_blocked": "dependency_blocked",
            "illegal_tool_requested": "illegal_tool_requested",
            "tool_loop_timeout": "tool_loop_timeout",
            "tool_loop_max_rounds_exceeded": "tool_loop_max_rounds_exceeded",
            "boundary_violation": "boundary_violation",
            "command_not_declared": "command_not_declared",
            "silent_provider_fallback": "silent_provider_fallback",
            "provider_error": "provider_error",
        }
        for event_type in event_types:
            if event_type in type_risk_map:
                found.add(type_risk_map[event_type])
        for risk in acceptance_risks:
            if risk in type_risk_map:
                found.add(risk)
        payload_sources = [
            json.dumps(export_payload, default=str),
            json.dumps(archive_payload, default=str),
            json.dumps(agent_results, default=str),
            json.dumps(scan_context.get("event_payloads", []), default=str),
        ]
        combined = " ".join(payload_sources) + " " + stdout_stderr_text
        risk_codes = set(type_risk_map.keys())
        report_lower = report_text.lower()
        for rc in risk_codes:
            negated = f"no {rc}" in report_lower or f"not {rc}" in report_lower
            if not negated and rc in combined.lower():
                found.add(rc)
        return sorted(found)

    # Scene F preflight
    if args.provider == "claude_cli":
        if args.coverage_percent is None:
            sc = make_status_context(cm_raw_status, cm_normalized, args.coverage_percent)
            write_scene_f_status(output_dir, args.scenario, "fail", reason="--coverage-percent is required for claude_cli", extra=sc)
            raise SystemExit(1)

        sc = make_status_context(cm_raw_status, cm_normalized, args.coverage_percent)
        if cm_normalized == "fail":
            write_scene_f_status(output_dir, args.scenario, "fail", reason=f"codebase_memory_status not recognized: {cm_raw_status}", extra=sc)
            raise SystemExit(1)
        if (
            cm_normalized == "missing"
            or not args.codebase_memory_project
            or args.codebase_memory_nodes is None
            or args.codebase_memory_edges is None
            or not args.architecture_status
        ):
            write_scene_f_status(
                output_dir,
                args.scenario,
                "fail",
                reason="codebase-memory params incomplete for claude_cli",
                extra={
                    **sc,
                    "project": bool(args.codebase_memory_project),
                    "nodes": args.codebase_memory_nodes,
                    "edges": args.codebase_memory_edges,
                    "architecture": bool(args.architecture_status),
                },
            )
            raise SystemExit(1)

        doctor_cmd = [sys.executable, "-m", "squad_runtime", "agents", "doctor"]
        doctor_completed = subprocess.run(doctor_cmd, cwd=repo_root, env=env, text=True, capture_output=True, encoding="utf-8", errors="replace")
        (output_dir / "provider-doctor.stdout.txt").write_text(doctor_completed.stdout or "", encoding="utf-8")
        (output_dir / "provider-doctor.stderr.txt").write_text(doctor_completed.stderr or "", encoding="utf-8")

        if doctor_completed.returncode != 0:
            write_scene_f_status(
                output_dir, args.scenario, "environment_blocked", reason="agents doctor failed", extra={**sc, "doctor_returncode": doctor_completed.returncode}
            )
            write_scene_f_summary(output_dir, [args.scenario])
            raise SystemExit(0)

        try:
            doctor_data = json.loads(doctor_completed.stdout)
        except json.JSONDecodeError:
            write_scene_f_status(output_dir, args.scenario, "environment_blocked", reason="agents doctor output is not JSON", extra=sc)
            write_scene_f_summary(output_dir, [args.scenario])
            raise SystemExit(0) from None

        (output_dir / "provider-doctor.json").write_text(json.dumps(doctor_data, ensure_ascii=False, indent=2), encoding="utf-8")
        claude_info = next((p for p in doctor_data.get("providers", []) if p.get("provider") == "claude_cli"), None)
        if not claude_info or not claude_info.get("available") or claude_info.get("provider_type") != "real_llm" or not claude_info.get("identity_verified"):
            providers_summary = [
                {"provider": p.get("provider"), "available": p.get("available"), "provider_type": p.get("provider_type")}
                for p in doctor_data.get("providers", [])
            ]
            write_scene_f_status(
                output_dir,
                args.scenario,
                "environment_blocked",
                reason="claude_cli preflight failed",
                extra={
                    **sc,
                    "providers_summary": providers_summary,
                    "claude_cli": {
                        "available": claude_info.get("available") if claude_info else False,
                        "provider_type": claude_info.get("provider_type") if claude_info else "N/A",
                        "identity_verified": claude_info.get("identity_verified") if claude_info else False,
                    },
                },
            )
            write_scene_f_summary(output_dir, [args.scenario])
            raise SystemExit(0)

    all_scenario_names: list[str] = []
    for round_num in range(1, args.rounds + 1):
        scenario_name = f"{args.scenario}-r{round_num}" if args.rounds > 1 else args.scenario
        all_scenario_names.append(scenario_name)

        try:
            result = run_scenario(squad_dir_resolved, scenario_name, provider=args.provider, output_dir=output_dir)

            shutil.copy(result["archive_path"], output_dir / f"archive-{scenario_name}.json")

            with open(output_dir / f"analytics-{scenario_name}.json", "w", encoding="utf-8") as f:
                json.dump(result["analytics"], f, ensure_ascii=False, indent=2)

            export_payload_text = (output_dir / f"FULL_DATA_LOG-{scenario_name}.json").read_text(encoding="utf-8")
            archive_payload_text = (output_dir / f"archive-{scenario_name}.json").read_text(encoding="utf-8")
            export_payload = json.loads(export_payload_text)
            archive_payload = json.loads(archive_payload_text)
            required_keys = {"run", "nodes", "gates", "agentResults", "events"}
            for key in required_keys:
                check(key in export_payload, f"export missing {key}")
                check(key in archive_payload, f"archive missing {key}")

            # Scene D check
            rt_check = Runtime.create(squad_dir_resolved)
            try:
                final_nodes = rt_check.list_nodes(result["run_id"])
                check(len(final_nodes) == 10, f"Expected 10 nodes, got {len(final_nodes)}")
                for n in final_nodes:
                    check(n.status == NodeStatus.PASS, f"{n.owner_agent_id}: {n.status.value}")

                expected_gates = {"test_gate": "pass", "code_review_gate": "pass", "reality_checker_gate": "pass", "release_gate": "pass"}
                actual_gates = rt_check.list_gate_states(result["run_id"])
                gate_map = {g["gateName"]: g["status"] for g in actual_gates}
                check(gate_map == expected_gates, f"Gate mismatch: {gate_map}")

                analytics = result["analytics"]
                for field_name in ("event_type_distribution", "provider_usage", "gate_summary", "result_count"):
                    check(field_name in analytics, f"analytics missing {field_name}")
                check(isinstance(analytics["event_type_distribution"], dict), "event_type_distribution is not dict")
                check(isinstance(analytics["provider_usage"], dict), "provider_usage is not dict")
                check(isinstance(analytics["gate_summary"], dict), "gate_summary is not dict")
                check(isinstance(analytics["result_count"], int), "result_count is not int")
                check(analytics["gate_summary"] == gate_map, f"analytics.gate_summary mismatch: {analytics['gate_summary']} vs {gate_map}")
                actual_results = rt_check.list_agent_results(result["run_id"])
                check(analytics["result_count"] == len(actual_results), "analytics.result_count mismatch")
                required_events = {"run_created", "node_created", "llm_session_started", "llm_session_completed", "agent_result_submitted", "gate_decision"}
                actual_types = set(analytics["event_type_distribution"].keys())
                missing = required_events - actual_types
                check(not missing, f"Missing event types: {missing}. Got: {actual_types}")
                check(set(analytics["provider_usage"].keys()) == {args.provider}, f"Expected {args.provider}, got {analytics['provider_usage']}")
            finally:
                rt_check.close()

            # acceptance-report
            report_path = output_dir / f"acceptance-report-{scenario_name}.md"
            cmd = [sys.executable, "-m", "squad_runtime", "acceptance-report", result["run_id"], "--output", str(report_path)]
            if args.provider == "claude_cli":
                cmd += ["--coverage-percent", str(args.coverage_percent)]
                cmd += ["--codebase-memory-status", cm_normalized]
                if args.codebase_memory_project:
                    cmd += ["--codebase-memory-project", args.codebase_memory_project]
                cmd += ["--codebase-memory-nodes", str(args.codebase_memory_nodes)]
                cmd += ["--codebase-memory-edges", str(args.codebase_memory_edges)]
                if args.architecture_status:
                    cmd += ["--architecture-status", args.architecture_status]

            completed = subprocess.run(cmd, cwd=repo_root, env=env, text=True, capture_output=True)
            (output_dir / f"acceptance-report-{scenario_name}.stdout.txt").write_text(completed.stdout, encoding="utf-8")
            (output_dir / f"acceptance-report-{scenario_name}.stderr.txt").write_text(completed.stderr, encoding="utf-8")
            check(completed.returncode == 0, f"acceptance-report failed (exit {completed.returncode}): {completed.stderr[:500]}")
            report_text = report_path.read_text(encoding="utf-8")

            if args.provider == "fake_cli":
                check("Conclusion: FAIL" in report_text, f"Expected FAIL for fake_cli:\n{report_text[:500]}")
                fake_parsed = parse_acceptance_risks(completed.stdout, report_text)
                check(fake_parsed["parsed"], "Cannot parse fake_cli acceptance-report risks")
                fake_risks = fake_parsed["risks"]
                required_provider_risks = {"required_provider_not_claude_cli", "required_provider_not_real_llm"}
                missing_risks = required_provider_risks - set(fake_risks)
                check(not missing_risks, f"Missing required provider risks: {missing_risks}. Got: {fake_risks}")
                extra_risks = (
                    set(fake_risks)
                    - required_provider_risks
                    - {"coverage_baseline_created_requires_rerun", "codebase_memory_not_indexed", "codebase_architecture_empty"}
                )
                if extra_risks:
                    print(json.dumps({"extra_risks": list(extra_risks), "all_risks": fake_risks}, indent=2))
            else:
                # Scene F acceptance
                try:
                    parsed = parse_acceptance_risks(completed.stdout, report_text)
                    if not parsed["parsed"]:
                        write_scene_f_status(
                            output_dir,
                            scenario_name,
                            "fail",
                            reason="Cannot parse acceptance-report risks",
                            extra=make_status_context(cm_raw_status, cm_normalized, args.coverage_percent),
                        )
                        check(False, "Cannot parse acceptance-report risks from stdout or markdown")

                    initial_risks: list[str] = []
                    final_risks: list[str] = []
                    baseline_retry_needed = False

                    risks = parsed["risks"]
                    if parsed["conclusion"] == "PASS":
                        check(risks == [], f"PASS with non-empty risks: {risks}")
                        final_risks = risks
                    else:
                        initial_risks = risks
                        if set(risks) == {"coverage_baseline_created_requires_rerun"}:
                            baseline_retry_needed = True
                        else:
                            write_scene_f_status(
                                output_dir,
                                scenario_name,
                                "fail",
                                reason=f"non-baseline risks: {risks}",
                                run_id=result["run_id"],
                                extra=make_status_context(cm_raw_status, cm_normalized, args.coverage_percent),
                            )
                            check(False, f"claude_cli acceptance FAIL with risks: {risks}")

                    baseline_initial_text = report_text
                    baseline_initial_stdout = completed.stdout
                    baseline_initial_stderr = completed.stderr
                    completed2 = None

                    if baseline_retry_needed:
                        (output_dir / f"acceptance-report-{scenario_name}.initial.md").write_text(baseline_initial_text, encoding="utf-8")
                        (output_dir / f"acceptance-report-{scenario_name}.initial.stdout.txt").write_text(baseline_initial_stdout, encoding="utf-8")
                        (output_dir / f"acceptance-report-{scenario_name}.initial.stderr.txt").write_text(baseline_initial_stderr, encoding="utf-8")

                        completed2 = subprocess.run(cmd, cwd=repo_root, env=env, text=True, capture_output=True)
                        check(completed2.returncode == 0, f"acceptance-report retry failed (exit {completed2.returncode}): {completed2.stderr[:500]}")
                        (output_dir / f"acceptance-report-{scenario_name}.retry.stdout.txt").write_text(completed2.stdout, encoding="utf-8")
                        (output_dir / f"acceptance-report-{scenario_name}.retry.stderr.txt").write_text(completed2.stderr, encoding="utf-8")
                        report_text = report_path.read_text(encoding="utf-8")
                        check("Conclusion: PASS" in report_text, f"claude_cli acceptance FAIL after baseline init:\n{report_text[:500]}")
                        (output_dir / f"acceptance-report-{scenario_name}.stdout.txt").write_text(completed2.stdout, encoding="utf-8")
                        (output_dir / f"acceptance-report-{scenario_name}.stderr.txt").write_text(completed2.stderr, encoding="utf-8")
                        final_parsed = parse_acceptance_risks(completed2.stdout, report_text)
                        check(
                            final_parsed["parsed"] and final_parsed["conclusion"] == "PASS" and final_parsed["risks"] == [],
                            f"retry did not produce clean PASS: conclusion={final_parsed['conclusion']} risks={final_parsed['risks']}",
                        )
                        final_risks = final_parsed["risks"]
                    else:
                        final_risks = risks

                    # Structured risk scan
                    rt_scan = Runtime.create(squad_dir_resolved)
                    scan_ctx: dict = {"event_types": set(), "event_payloads": []}
                    try:
                        for event in rt_scan.events.query(result["run_id"], limit=100000).events:
                            scan_ctx["event_types"].add(getattr(event, "type", ""))
                            scan_ctx["event_payloads"].append(getattr(event, "payload", {}))
                    finally:
                        rt_scan.close()

                    scan_agent_results = actual_results
                    stdout_stderr_text = f"{completed.stdout}\n{completed.stderr}"
                    if completed2:
                        stdout_stderr_text += f"\n{completed2.stdout}\n{completed2.stderr}"

                    scan_report = report_text
                    if baseline_retry_needed:
                        scan_report = baseline_initial_text + "\n" + report_text

                    found_risks = structured_risk_scan(
                        scan_ctx, scan_report, final_risks, export_payload, archive_payload, scan_agent_results, stdout_stderr_text
                    )
                    if found_risks:
                        write_scene_f_status(
                            output_dir,
                            scenario_name,
                            "fail",
                            reason=f"risk codes: {found_risks}",
                            run_id=result["run_id"],
                            extra=make_status_context(
                                cm_raw_status, cm_normalized, args.coverage_percent, {"initial_risks": initial_risks, "final_risks": final_risks}
                            ),
                        )
                        check(False, f"Scene F found risk codes: {found_risks}")

                    write_scene_f_status(
                        output_dir,
                        scenario_name,
                        "pass",
                        reason="acceptance PASS, no risks",
                        run_id=result["run_id"],
                        extra=make_status_context(
                            cm_raw_status,
                            cm_normalized,
                            args.coverage_percent,
                            {
                                "baseline_retry_needed": baseline_retry_needed,
                                "initial_risks": initial_risks,
                                "final_risks": final_risks,
                            },
                        ),
                    )
                except SystemExit:
                    raise
                except Exception as e:
                    write_scene_f_status(
                        output_dir,
                        scenario_name,
                        "fail",
                        reason="Scene F exception",
                        run_id=result.get("run_id") if result else "",
                        extra=make_status_context(
                            cm_raw_status, cm_normalized, args.coverage_percent, {"exception_type": type(e).__name__, "exception_message": str(e)}
                        ),
                    )
                    raise

            print(json.dumps({"round": round_num, "provider": args.provider, **result}, default=str, indent=2))
        except Exception as e:
            if args.provider == "claude_cli":
                write_scene_f_status(
                    output_dir,
                    scenario_name,
                    "fail",
                    reason="round exception",
                    extra=make_status_context(
                        cm_raw_status, cm_normalized, args.coverage_percent, {"exception_type": type(e).__name__, "exception_message": str(e)}
                    ),
                )
            raise

    if args.provider == "claude_cli" and all_scenario_names:
        write_scene_f_summary(output_dir, all_scenario_names)
