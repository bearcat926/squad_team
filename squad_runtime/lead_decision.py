from __future__ import annotations

from dataclasses import dataclass

from .runtime import Runtime


@dataclass(frozen=True)
class DecisionChangeSet:
    directive_id: str
    bypass_attempt: bool
    actions: list[str]


class LeadDecisionEngine:
    """Converts user directives into auditable decisions without mutating task state directly."""

    BYPASS_TERMS = ("release_go", "mark as done", "gate pass", "skip gate", "force release")

    def __init__(self, runtime: Runtime):
        self.runtime = runtime

    def apply_directive(self, run_id: str, message: str) -> DecisionChangeSet:
        directive_id = self.runtime.record_directive(run_id, message)
        lower_message = message.lower()
        bypass_attempt = any(term in lower_message for term in self.BYPASS_TERMS)
        actions: list[str] = ["directive_recorded"]
        if bypass_attempt:
            self.runtime.events.append(
                run_id,
                "gate_bypass_attempt",
                {"directiveId": directive_id, "message": message},
                critical=True,
            )
            actions.append("gate_bypass_attempt_recorded")
        self.runtime.events.append(
            run_id,
            "decision_applied",
            {"directiveId": directive_id, "actions": actions, "bypassAttempt": bypass_attempt},
            critical=True,
        )
        return DecisionChangeSet(directive_id=directive_id, bypass_attempt=bypass_attempt, actions=actions)
