"""Repository for squad_runs table."""

from __future__ import annotations

import sqlite3

from ..models import SquadRun


class RunRepository:
    """CRUD operations for the squad_runs table."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert(self, run_id: str, goal: str, status: str, version: int, rule_version: str, schema_version: str, agent_contract_version: str) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO squad_runs
                    (id, goal, status, version, rule_version, schema_version, agent_contract_version)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, goal, status, version, rule_version, schema_version, agent_contract_version),
            )

    def get(self, run_id: str) -> SquadRun:
        row = self.conn.execute("SELECT * FROM squad_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return self._row_to_run(row)

    def list_all(self) -> list[SquadRun]:
        rows = self.conn.execute("SELECT * FROM squad_runs ORDER BY rowid ASC").fetchall()
        return [self._row_to_run(row) for row in rows]

    def increment_version(self, run_id: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE squad_runs SET version = version + 1 WHERE id = ?", (run_id,))

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> SquadRun:
        return SquadRun(
            id=row["id"],
            goal=row["goal"],
            status=row["status"],
            version=int(row["version"]),
            rule_version=row["rule_version"],
            schema_version=row["schema_version"],
            agent_contract_version=row["agent_contract_version"],
        )
