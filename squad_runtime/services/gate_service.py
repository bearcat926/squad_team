"""Service for gate state operations."""

from __future__ import annotations

from typing import Any

from ..event_store import EventStore
from ..repositories.gate_repository import GateRepository


class GateService:
    """Business logic for gate state management."""

    def __init__(self, gate_repo: GateRepository, events: EventStore):
        self._repo = gate_repo
        self._events = events

    def upsert_gate_state(self, run_id: str, gate_name: str, status: str, reason: str, blocked_reason_code: str | None = None) -> None:
        self._repo.upsert(run_id, gate_name, status, reason, blocked_reason_code)
        self._events.append(
            run_id,
            "gate_status_changed",
            {"gateName": gate_name, "status": status, "reason": reason, "blockedReasonCode": blocked_reason_code},
            critical=True,
        )

    def list_gate_states(self, run_id: str) -> list[dict[str, Any]]:
        return self._repo.list_by_run(run_id)
