"""Unit tests for EventRepository delegation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from squad_runtime.event_store import EventStore
from squad_runtime.repositories.event_repository import EventRepository


@pytest.fixture
def store(tmp_path: Path):
    s = EventStore(tmp_path)
    yield s
    s.close()


@pytest.fixture
def repo(store: EventStore):
    r = EventRepository(store)
    yield r
    r.close()


class TestEventRepository:
    def test_append_delegates_to_store(self, repo: EventRepository):
        event = repo.append("run-1", "test_event", {"key": "value"}, critical=True)
        assert event.run_id == "run-1"
        assert event.type == "test_event"
        assert event.payload == {"key": "value"}
        assert event.critical is True

    def test_query_delegates_to_store(self, repo: EventRepository):
        repo.append("run-1", "ev1", {"n": 1})
        repo.append("run-1", "ev2", {"n": 2})
        page = repo.query("run-1", limit=10)
        assert len(page.events) == 2
        assert page.events[0].type == "ev1"
        assert page.events[1].type == "ev2"

    def test_query_with_cursor(self, repo: EventRepository):
        repo.append("run-1", "ev1", {"n": 1})
        repo.append("run-1", "ev2", {"n": 2})
        repo.append("run-1", "ev3", {"n": 3})
        page = repo.query("run-1", cursor=1, limit=10)
        assert len(page.events) == 2
        assert page.events[0].type == "ev2"

    def test_query_limit_zero(self, repo: EventRepository):
        repo.append("run-1", "ev1", {"n": 1})
        page = repo.query("run-1", limit=0)
        assert len(page.events) == 0

    def test_query_limit_one_with_next_cursor(self, repo: EventRepository):
        repo.append("run-1", "ev1", {"n": 1})
        repo.append("run-1", "ev2", {"n": 2})
        page = repo.query("run-1", limit=1)
        assert len(page.events) == 1
        assert page.next_cursor == page.events[-1].sequence_number

    def test_query_different_run_ids(self, repo: EventRepository):
        repo.append("run-1", "a", {})
        repo.append("run-2", "b", {})
        assert len(repo.query("run-1", limit=10).events) == 1
        assert len(repo.query("run-2", limit=10).events) == 1
        assert len(repo.query("run-3", limit=10).events) == 0

    def test_query_cursor_beyond_last(self, repo: EventRepository):
        repo.append("run-1", "ev1", {"n": 1})
        page = repo.query("run-1", cursor=999, limit=10)
        assert len(page.events) == 0

    def test_query_cursor_zero_returns_all_events(self, repo: EventRepository):
        repo.append("run-1", "ev1", {"n": 1})
        repo.append("run-1", "ev2", {"n": 2})
        page = repo.query("run-1", cursor=0, limit=10)
        assert [e.type for e in page.events] == ["ev1", "ev2"]

    def test_close_delegates_to_store(self, tmp_path: Path):
        store = EventStore(tmp_path)
        repo = EventRepository(store)
        repo.close()
        with pytest.raises(sqlite3.ProgrammingError):
            store.conn.execute("SELECT 1")
