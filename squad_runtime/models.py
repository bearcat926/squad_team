from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .state import NodeStatus


@dataclass(frozen=True)
class SquadRun:
    id: str
    goal: str
    status: str
    version: int
    rule_version: str
    schema_version: str
    agent_contract_version: str


@dataclass(frozen=True)
class TaskNode:
    id: str
    run_id: str
    title: str
    type: str
    owner_agent_id: str
    status: NodeStatus
    blocked_reason_code: str | None
    checkpoint_id: str
    replaced_by_node_id: str | None = None


@dataclass(frozen=True)
class SquadEvent:
    id: str
    run_id: str
    sequence_number: int
    type: str
    payload: dict[str, Any]
    critical: bool
    created_at: str


@dataclass(frozen=True)
class EventPage:
    events: list[SquadEvent]
    next_cursor: int | None = None


@dataclass(frozen=True)
class GateDecision:
    gate_name: str
    status: str
    reason: str
    blocking: bool = True
    blocked_reason_code: str | None = None
    details: dict[str, Any] | None = None
