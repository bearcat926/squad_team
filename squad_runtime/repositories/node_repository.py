"""Repository for task_nodes table."""

from __future__ import annotations

import sqlite3

from ..models import TaskNode
from ..state import NodeStatus


class NodeRepository:
    """CRUD operations for the task_nodes table."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert(
        self,
        node_id: str,
        run_id: str,
        title: str,
        node_type: str,
        owner_agent_id: str,
        status: NodeStatus,
        checkpoint_id: str,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO task_nodes
                    (id, run_id, title, type, owner_agent_id, status, blocked_reason_code, checkpoint_id, replaced_by_node_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (node_id, run_id, title, node_type, owner_agent_id, status.value, None, checkpoint_id, None),
            )

    def get(self, node_id: str) -> TaskNode:
        row = self.conn.execute("SELECT * FROM task_nodes WHERE id = ?", (node_id,)).fetchone()
        if row is None:
            raise KeyError(node_id)
        return self._row_to_node(row)

    def list_by_run(self, run_id: str) -> list[TaskNode]:
        rows = self.conn.execute("SELECT * FROM task_nodes WHERE run_id = ? ORDER BY rowid ASC", (run_id,)).fetchall()
        return [self._row_to_node(row) for row in rows]

    def update_status(self, node_id: str, from_status: NodeStatus, to_status: NodeStatus, blocked_reason_code: str | None) -> None:
        with self.conn:
            self.conn.execute(
                """
                UPDATE task_nodes
                SET status = ?, blocked_reason_code = ?
                WHERE id = ? AND status = ?
                """,
                (to_status.value, blocked_reason_code, node_id, from_status.value),
            )

    def list_by_status(self, status: NodeStatus) -> list[TaskNode]:
        rows = self.conn.execute("SELECT id FROM task_nodes WHERE status = ?", (status.value,)).fetchall()
        return [self.get(row["id"]) for row in rows]

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> TaskNode:
        return TaskNode(
            id=row["id"],
            run_id=row["run_id"],
            title=row["title"],
            type=row["type"],
            owner_agent_id=row["owner_agent_id"],
            status=NodeStatus(row["status"]),
            blocked_reason_code=row["blocked_reason_code"],
            checkpoint_id=row["checkpoint_id"],
            replaced_by_node_id=row["replaced_by_node_id"],
        )
