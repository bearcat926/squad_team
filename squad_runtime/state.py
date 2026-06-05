from __future__ import annotations

from enum import StrEnum


class NodeStatus(StrEnum):
    TODO = "todo"
    READY = "ready"
    RUNNING = "running"
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"
    AGENT_UNAVAILABLE = "agent_unavailable"
    PROGRESS_TIMEOUT = "progress_timeout"
    CANCELED = "canceled"
    STALE = "stale"
    DONE = "done"


class InvalidTransition(ValueError):
    """Raised when a node state transition is not allowed."""


BLOCKED_REASON_CODES = {
    "missing_test_pass",
    "missing_review_pass",
    "invalid_agent_result",
    "gate_dependency_failed",
    "agent_unavailable",
    "progress_timeout",
    "directive_conflict",
    "transition_conflict",
    "artifact_path_invalid",
    "checkpoint_mismatch",
}


ALLOWED_TRANSITIONS: dict[NodeStatus, set[NodeStatus]] = {
    NodeStatus.TODO: {NodeStatus.READY, NodeStatus.BLOCKED, NodeStatus.CANCELED, NodeStatus.STALE},
    NodeStatus.READY: {NodeStatus.RUNNING, NodeStatus.BLOCKED, NodeStatus.CANCELED, NodeStatus.STALE},
    NodeStatus.RUNNING: {
        NodeStatus.PASS,
        NodeStatus.FAIL,
        NodeStatus.BLOCKED,
        NodeStatus.CANCELED,
        NodeStatus.AGENT_UNAVAILABLE,
        NodeStatus.PROGRESS_TIMEOUT,
        NodeStatus.STALE,
    },
    NodeStatus.AGENT_UNAVAILABLE: {NodeStatus.READY, NodeStatus.CANCELED},
    NodeStatus.PROGRESS_TIMEOUT: {NodeStatus.READY, NodeStatus.CANCELED},
    NodeStatus.BLOCKED: {NodeStatus.READY, NodeStatus.CANCELED, NodeStatus.STALE},
    NodeStatus.FAIL: {NodeStatus.READY, NodeStatus.CANCELED, NodeStatus.STALE},
    NodeStatus.PASS: {NodeStatus.STALE, NodeStatus.DONE},
    NodeStatus.CANCELED: {NodeStatus.DONE},
    NodeStatus.STALE: set(),
    NodeStatus.DONE: set(),
}


def ensure_transition_allowed(from_status: NodeStatus, to_status: NodeStatus) -> None:
    if to_status not in ALLOWED_TRANSITIONS[from_status]:
        raise InvalidTransition(f"Cannot transition {from_status.value} -> {to_status.value}")
