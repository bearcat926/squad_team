"""Integration tests for database schema initialization."""

from __future__ import annotations

from pathlib import Path

import pytest

from squad_runtime.infrastructure.database import Database
from squad_runtime.infrastructure.schema import init_schema


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    init_schema(database.conn)
    return database


def test_database_creates_connection_with_wal_mode(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    mode = database.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
    database.close()


def test_database_sets_busy_timeout(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    timeout = database.conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert timeout == 5000
    database.close()


def test_schema_creates_all_expected_tables(db: Database):
    tables = {row[0] for row in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    expected = {
        "squad_runs",
        "user_directives",
        "task_nodes",
        "gate_states",
        "agent_results",
        "evidence_items",
        "review_findings",
        "review_findings_history",
        "artifacts",
        "dispatches",
        "context_bundles",
        "provider_health",
    }
    assert expected <= tables


def test_schema_is_idempotent(db: Database):
    init_schema(db.conn)
    tables = {row[0] for row in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "squad_runs" in tables


def test_agent_results_has_provider_columns(db: Database):
    columns = {row[1] for row in db.conn.execute("PRAGMA table_info(agent_results)").fetchall()}
    assert "provider_type" in columns
    assert "provider_identity_verified" in columns
