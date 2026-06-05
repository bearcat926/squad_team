"""Repository for gate_states table."""

from __future__ import annotations

import sqlite3
from typing import Any


class GateRepository:
    """CRUD operations for the gate_states table."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert(self, run_id: str, gate_name: str, status: str, reason: str, blocked_reason_code: str | None = None) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO gate_states (run_id, gate_name, status, blocked_reason_code, reason)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id, gate_name) DO UPDATE SET
                    status = excluded.status,
                    blocked_reason_code = excluded.blocked_reason_code,
                    reason = excluded.reason
                """,
                (run_id, gate_name, status, blocked_reason_code, reason),
            )

    def list_by_run(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT gate_name, status, blocked_reason_code, reason FROM gate_states WHERE run_id = ? ORDER BY gate_name ASC",
            (run_id,),
        ).fetchall()
        return [
            {
                "gateName": row["gate_name"],
                "status": row["status"],
                "blockedReasonCode": row["blocked_reason_code"],
                "reason": row["reason"],
            }
            for row in rows
        ]
