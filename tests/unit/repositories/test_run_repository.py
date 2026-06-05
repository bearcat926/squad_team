"""Unit tests for RunRepository."""

from __future__ import annotations

from pathlib import Path

import pytest

from squad_runtime.infrastructure.database import Database
from squad_runtime.infrastructure.schema import init_schema
from squad_runtime.repositories.run_repository import RunRepository


@pytest.fixture()
def repo(tmp_path: Path) -> RunRepository:
    db = Database(tmp_path / "test.db")
    init_schema(db.conn)
    return RunRepository(db.conn)


def test_insert_and_get(repo: RunRepository):
    repo.insert("run-1", "build something", "planning", 0, "v1", "v1", "v1")
    run = repo.get("run-1")
    assert run.id == "run-1"
    assert run.goal == "build something"
    assert run.status == "planning"
    assert run.version == 0


def test_get_missing_raises_key_error(repo: RunRepository):
    with pytest.raises(KeyError):
        repo.get("nonexistent")


def test_list_all(repo: RunRepository):
    repo.insert("run-1", "first", "planning", 0, "v1", "v1", "v1")
    repo.insert("run-2", "second", "planning", 0, "v1", "v1", "v1")
    runs = repo.list_all()
    assert len(runs) == 2
    assert runs[0].id == "run-1"
    assert runs[1].id == "run-2"


def test_increment_version(repo: RunRepository):
    repo.insert("run-1", "goal", "planning", 0, "v1", "v1", "v1")
    repo.increment_version("run-1")
    run = repo.get("run-1")
    assert run.version == 1
