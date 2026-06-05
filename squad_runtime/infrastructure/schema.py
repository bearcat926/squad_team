"""Schema DDL for Squad Runtime database."""

from __future__ import annotations

import sqlite3


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables and apply migrations."""
    with conn:
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

        for column_name, column_sql in [
            ("provider_type", "ALTER TABLE agent_results ADD COLUMN provider_type TEXT NOT NULL DEFAULT 'deterministic'"),
            ("provider_identity_verified", "ALTER TABLE agent_results ADD COLUMN provider_identity_verified INTEGER NOT NULL DEFAULT 0"),
        ]:
            existing = [row[1] for row in conn.execute("PRAGMA table_info(agent_results)").fetchall()]
            if column_name not in existing:
                conn.execute(column_sql)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS provider_health (
                provider TEXT PRIMARY KEY,
                available INTEGER NOT NULL,
                detail TEXT NOT NULL,
                checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)
