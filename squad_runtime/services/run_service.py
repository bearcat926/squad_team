"""Service for run lifecycle operations."""

from __future__ import annotations

import uuid

from ..event_store import EventStore
from ..models import SquadRun
from ..repositories.run_repository import RunRepository


class RunService:
    """Business logic for creating, reading, listing, and archiving runs."""

    def __init__(self, run_repo: RunRepository, events: EventStore):
        self._repo = run_repo
        self._events = events

    def create_run(
        self,
        goal: str,
        rule_version: str = "v1",
        schema_version: str = "v1",
        agent_contract_version: str = "v1",
    ) -> SquadRun:
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        self._repo.insert(run_id, goal, "planning", 0, rule_version, schema_version, agent_contract_version)
        self._events.append(run_id, "run_created", {"goal": goal}, critical=True)
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> SquadRun:
        return self._repo.get(run_id)

    def list_runs(self) -> list[SquadRun]:
        return self._repo.list_all()
