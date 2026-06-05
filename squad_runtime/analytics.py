"""Event analytics engine for Squad Runtime.

Computes summary statistics across runs, providers, gates, and events.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .runtime import Runtime


class AnalyticsEngine:
    """Compute analytics summaries from runtime data."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime

    def compute_summary(self, run_id: str | None = None) -> dict[str, Any]:
        """Compute analytics summary.

        If *run_id* is given, scope to that run. Otherwise aggregate across
        all runs.
        """
        runs = self.runtime.list_runs()
        if run_id:
            runs = [r for r in runs if r.id == run_id]

        if not runs:
            return self._empty_summary()

        all_results: list[dict[str, Any]] = []
        all_gates: list[dict[str, Any]] = []
        all_events: list[Any] = []
        provider_counter: Counter[str] = Counter()

        for run in runs:
            results = self.runtime.list_agent_results(run.id)
            all_results.extend(results)
            all_gates.extend(self.runtime.list_gate_states(run.id))
            all_events.extend(self.runtime.events.query(run.id, limit=100000).events)
            for result in results:
                provider_counter[result["providerUsed"]] += 1

        total = len(all_results)
        pass_count = sum(1 for r in all_results if r["status"] == "pass")
        fail_count = sum(1 for r in all_results if r["status"] == "fail")
        blocked_count = sum(1 for r in all_results if r["status"] == "blocked")

        confidences = [r["confidence"] for r in all_results if r["confidence"] is not None]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        event_type_counter: Counter[str] = Counter()
        for event in all_events:
            event_type_counter[event.type] += 1

        gate_summary: dict[str, str] = {}
        for gate in all_gates:
            gate_summary[gate["gateName"]] = gate["status"]

        return {
            "run_count": len(runs),
            "result_count": total,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "blocked_count": blocked_count,
            "success_rate": round(pass_count / total * 100, 1) if total else 0.0,
            "failure_rate": round(fail_count / total * 100, 1) if total else 0.0,
            "avg_confidence": round(avg_confidence, 3),
            "provider_usage": dict(provider_counter.most_common()),
            "gate_summary": gate_summary,
            "event_type_distribution": dict(event_type_counter.most_common()),
        }

    @staticmethod
    def _empty_summary() -> dict[str, Any]:
        return {
            "run_count": 0,
            "result_count": 0,
            "pass_count": 0,
            "fail_count": 0,
            "blocked_count": 0,
            "success_rate": 0.0,
            "failure_rate": 0.0,
            "avg_confidence": 0.0,
            "provider_usage": {},
            "gate_summary": {},
            "event_type_distribution": {},
        }
