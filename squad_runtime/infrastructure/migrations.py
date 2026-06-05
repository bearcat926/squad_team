"""Lightweight schema migration system for Squad Runtime.

Tracks applied migrations in a ``schema_version`` table so that repeated
initialisations are idempotent and older databases can be upgraded in-place.

Only *upgrade* is supported -- there is no downgrade.  For a local SQLite
project, rollback is handled via backup/restore (see ``backup_service``).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

# ---------------------------------------------------------------------------
# Individual migration steps
# ---------------------------------------------------------------------------


def _001_initial_schema(conn: sqlite3.Connection) -> None:
    """Create all core tables (mirrors the original ``init_schema`` DDL)."""

    conn.execute("""
        CREATE TABLE IF NOT EXISTS squad_runs (
            id TEXT PRIMARY KEY,
            goal TEXT NOT NULL,
            status TEXT NOT NULL,
            version INTEGER NOT NULL,
            rule_version TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            agent_contract_version TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_directives (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            source TEXT NOT NULL,
            message TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_nodes (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            title TEXT NOT NULL,
            type TEXT NOT NULL,
            owner_agent_id TEXT NOT NULL,
            status TEXT NOT NULL,
            blocked_reason_code TEXT,
            checkpoint_id TEXT NOT NULL,
            replaced_by_node_id TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gate_states (
            run_id TEXT NOT NULL,
            gate_name TEXT NOT NULL,
            status TEXT NOT NULL,
            blocked_reason_code TEXT,
            reason TEXT NOT NULL,
            PRIMARY KEY (run_id, gate_name)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_results (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            task_node_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            status TEXT NOT NULL,
            summary TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            artifacts_json TEXT NOT NULL,
            risks_json TEXT NOT NULL,
            next_actions_json TEXT NOT NULL,
            confidence REAL NOT NULL,
            worked_against_checkpoint TEXT NOT NULL,
            agent_contract_version TEXT NOT NULL,
            provider_used TEXT NOT NULL,
            provider_type TEXT NOT NULL DEFAULT 'deterministic',
            provider_identity_verified INTEGER NOT NULL DEFAULT 0,
            provider_fallback_triggered INTEGER NOT NULL DEFAULT 0,
            fallback_reason TEXT,
            synthetic INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS evidence_items (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            task_node_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            author_agent_id TEXT NOT NULL,
            content TEXT NOT NULL,
            immutable INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS review_findings (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            task_node_id TEXT NOT NULL,
            author_agent_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            superseded_by_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS review_findings_history (
            id TEXT PRIMARY KEY,
            finding_id TEXT NOT NULL,
            action TEXT NOT NULL,
            author_agent_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            task_node_id TEXT,
            name TEXT NOT NULL,
            path TEXT NOT NULL,
            type TEXT NOT NULL,
            author_agent_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dispatches (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            task_node_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS context_bundles (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            task_node_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS provider_health (
            provider TEXT PRIMARY KEY,
            available INTEGER NOT NULL,
            detail TEXT NOT NULL,
            checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _002_add_provider_fields(conn: sqlite3.Connection) -> None:
    """Ensure provider-related columns exist on ``agent_results``.

    Older databases created before these columns were added will be upgraded.
    Already-correct databases are left untouched.
    """

    existing = {row[1] for row in conn.execute("PRAGMA table_info(agent_results)").fetchall()}

    if "provider_type" not in existing:
        conn.execute("ALTER TABLE agent_results ADD COLUMN provider_type TEXT NOT NULL DEFAULT 'deterministic'")

    if "provider_identity_verified" not in existing:
        conn.execute("ALTER TABLE agent_results ADD COLUMN provider_identity_verified INTEGER NOT NULL DEFAULT 0")

    if "provider_fallback_triggered" not in existing:
        conn.execute("ALTER TABLE agent_results ADD COLUMN provider_fallback_triggered INTEGER NOT NULL DEFAULT 0")

    if "fallback_reason" not in existing:
        conn.execute("ALTER TABLE agent_results ADD COLUMN fallback_reason TEXT")

    if "synthetic" not in existing:
        conn.execute("ALTER TABLE agent_results ADD COLUMN synthetic INTEGER NOT NULL DEFAULT 0")


# ---------------------------------------------------------------------------
# Migration registry -- add new entries at the end.
# ---------------------------------------------------------------------------

MIGRATIONS: list[tuple[str, Callable[[sqlite3.Connection], Any]]] = [
    ("001_initial_schema", _001_initial_schema),
    ("002_add_provider_fields", _002_add_provider_fields),
]


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    """Create the tracking table if it does not already exist."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (" "  version TEXT PRIMARY KEY," "  applied_at TEXT NOT NULL" ")")


def run_migrations(conn: sqlite3.Connection) -> list[str]:
    """Apply all pending migrations in order.

    Returns a list of migration version strings that were applied during this
    call.  If no migrations are pending the list is empty.
    """

    applied: list[str] = []
    _ensure_version_table(conn)

    already_applied = {row[0] for row in conn.execute("SELECT version FROM schema_version").fetchall()}

    for version, fn in MIGRATIONS:
        if version not in already_applied:
            fn(conn)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, datetime('now'))",
                (version,),
            )
            applied.append(version)

    return applied
