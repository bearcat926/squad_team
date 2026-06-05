"""Unit tests for RunService."""

from __future__ import annotations

from pathlib import Path

import pytest

from squad_runtime.event_store import EventStore
from squad_runtime.infrastructure.database import Database
from squad_runtime.infrastructure.schema import init_schema
from squad_runtime.repositories.run_repository import RunRepository
from squad_runtime.services.run_service import RunService


@pytest.fixture()
def service(tmp_path: Path) -> RunService:
    db = Database(tmp_path / "test.db")
    init_schema(db.conn)
    events = EventStore(tmp_path / ".squad")
    repo = RunRepository(db.conn)
    return RunService(repo, events)


def test_create_run(service: RunService):
    run = service.create_run("build something")
    assert run.goal == "build something"
    assert run.status == "planning"
    assert run.version == 0
    assert run.id.startswith("run-")


def test_create_run_with_custom_versions(service: RunService):
    run = service.create_run("goal", rule_version="v2", schema_version="v3", agent_contract_version="v4")
    assert run.rule_version == "v2"
    assert run.schema_version == "v3"
    assert run.agent_contract_version == "v4"


def test_get_run(service: RunService):
    created = service.create_run("my goal")
    retrieved = service.get_run(created.id)
    assert retrieved.id == created.id
    assert retrieved.goal == "my goal"


def test_get_run_missing(service: RunService):
    with pytest.raises(KeyError):
        service.get_run("nonexistent")


def test_list_runs(service: RunService):
    service.create_run("first")
    service.create_run("second")
    runs = service.list_runs()
    assert len(runs) == 2
