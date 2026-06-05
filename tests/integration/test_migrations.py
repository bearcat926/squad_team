"""Integration tests for the lightweight migration system."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from squad_runtime.infrastructure.database import Database
from squad_runtime.infrastructure.migrations import MIGRATIONS, run_migrations


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    """Create a database and run all migrations."""
    database = Database(tmp_path / "test.db")
    run_migrations(database.conn)
    return database


# ---------------------------------------------------------------------------
# Empty database initialisation (first run)
# ---------------------------------------------------------------------------


def test_first_run_creates_schema_version_table(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    applied = run_migrations(database.conn)

    tables = {row[0] for row in database.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "schema_version" in tables
    assert len(applied) == len(MIGRATIONS)
    database.close()


def test_first_run_creates_all_core_tables(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    run_migrations(database.conn)

    tables = {row[0] for row in database.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
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
        "schema_version",
    }
    assert expected <= tables
    database.close()


def test_first_run_records_all_versions(db: Database):
    rows = db.conn.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
    recorded = [row[0] for row in rows]
    expected = [name for name, _ in MIGRATIONS]
    assert recorded == expected


# ---------------------------------------------------------------------------
# Idempotency -- repeated initialisation
# ---------------------------------------------------------------------------


def test_repeated_initialisation_is_idempotent(db: Database):
    """Running migrations twice does not duplicate rows or fail."""
    first_count = db.conn.execute("SELECT count(*) FROM schema_version").fetchone()[0]
    applied = run_migrations(db.conn)
    second_count = db.conn.execute("SELECT count(*) FROM schema_version").fetchone()[0]

    assert applied == []
    assert first_count == second_count


def test_tables_survive_repeated_init(db: Database):
    """Inserting data, then re-running migrations, does not lose data."""
    db.conn.execute(
        "INSERT INTO squad_runs (id, goal, status, version, rule_version, " "schema_version, agent_contract_version) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("run-1", "test", "active", 1, "v1", "v1", "v1"),
    )
    db.conn.commit()

    run_migrations(db.conn)

    row = db.conn.execute("SELECT id FROM squad_runs WHERE id = 'run-1'").fetchone()
    assert row is not None
    assert row[0] == "run-1"


# ---------------------------------------------------------------------------
# Old database upgrade (no schema_version table yet)
# ---------------------------------------------------------------------------


def test_old_database_gets_upgraded(tmp_path: Path):
    """A database that was created by the old init_schema path (no
    schema_version table) should be upgraded when run_migrations is called.
    """
    database = Database(tmp_path / "old.db")

    # Simulate the old path: create tables without schema_version tracking.
    from squad_runtime.infrastructure.schema import init_schema

    init_schema(database.conn)

    # schema_version table should NOT exist yet.
    tables = {row[0] for row in database.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "schema_version" not in tables

    # Now run the migration system.
    applied = run_migrations(database.conn)

    # schema_version table now exists and all migrations are recorded.
    tables = {row[0] for row in database.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "schema_version" in tables
    assert len(applied) == len(MIGRATIONS)
    database.close()


def test_old_database_with_data_preserved_after_upgrade(tmp_path: Path):
    database = Database(tmp_path / "old.db")
    from squad_runtime.infrastructure.schema import init_schema

    init_schema(database.conn)

    database.conn.execute(
        "INSERT INTO squad_runs (id, goal, status, version, rule_version, " "schema_version, agent_contract_version) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("run-legacy", "legacy goal", "completed", 1, "v1", "v1", "v1"),
    )
    database.conn.commit()

    run_migrations(database.conn)

    row = database.conn.execute("SELECT id, goal FROM squad_runs WHERE id = 'run-legacy'").fetchone()
    assert row is not None
    assert row[1] == "legacy goal"
    database.close()


# ---------------------------------------------------------------------------
# Migration failure triggers rollback
# ---------------------------------------------------------------------------


def test_migration_failure_triggers_rollback(tmp_path: Path):
    """If a migration step fails the transaction should be rolled back and
    the failed version should NOT appear in schema_version.
    """
    from squad_runtime.infrastructure import migrations as mig_module

    # We need at least one real migration to have run first so that we can
    # test that a *subsequent* failure does not corrupt state.
    database = Database(tmp_path / "fail.db")
    run_migrations(database.conn)

    # Inject a broken migration.
    original = list(mig_module.MIGRATIONS)
    try:
        mig_module.MIGRATIONS.append(("999_broken", lambda conn: conn.execute("INVALID SQL THAT WILL FAIL")))

        with pytest.raises(sqlite3.OperationalError):
            run_migrations(database.conn)

        # The broken version must not be persisted.
        versions = {row[0] for row in database.conn.execute("SELECT version FROM schema_version").fetchall()}
        assert "999_broken" not in versions
    finally:
        mig_module.MIGRATIONS[:] = original
        database.close()


def test_can_retry_after_failure(tmp_path: Path):
    """After a transient failure, the next call should re-apply only the
    missing migration.
    """
    database = Database(tmp_path / "retry.db")

    # Run the first migration function and record it as applied.
    database.conn.execute("CREATE TABLE IF NOT EXISTS schema_version (" "  version TEXT PRIMARY KEY," "  applied_at TEXT NOT NULL" ")")
    # Actually apply migration 001 so its tables exist.
    MIGRATIONS[0][1](database.conn)
    database.conn.execute("INSERT INTO schema_version (version, applied_at) VALUES ('001_initial_schema', datetime('now'))")
    database.conn.commit()

    applied = run_migrations(database.conn)
    # Only 002 (and any later) migrations should have been applied.
    assert "001_initial_schema" not in applied
    assert "002_add_provider_fields" in applied
    database.close()
