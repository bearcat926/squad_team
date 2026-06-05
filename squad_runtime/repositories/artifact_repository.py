"""Repository for agent_results, evidence_items, artifacts, and review_findings tables."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from ..agent_contracts import AgentResult


class ArtifactRepository:
    """CRUD operations for agent results, evidence, artifacts, and review findings."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # --- Agent Results ---

    def insert_agent_result(
        self,
        result_id: str,
        run_id: str,
        result: AgentResult,
        provider_used: str,
        provider_type: str,
        provider_identity_verified: bool,
        provider_fallback_triggered: bool,
        fallback_reason: str | None,
        synthetic: bool,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO agent_results
                    (id, run_id, task_node_id, agent_id, status, summary, evidence_json,
                     artifacts_json, risks_json, next_actions_json, confidence,
                     worked_against_checkpoint, agent_contract_version, provider_used,
                     provider_type, provider_identity_verified, provider_fallback_triggered, fallback_reason, synthetic)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    run_id,
                    result.taskNodeId,
                    result.agentId,
                    result.status,
                    result.summary,
                    json.dumps(result.evidence, ensure_ascii=False, sort_keys=True),
                    json.dumps(result.artifacts, ensure_ascii=False, sort_keys=True),
                    json.dumps(result.risks, ensure_ascii=False, sort_keys=True),
                    json.dumps(result.nextActions, ensure_ascii=False, sort_keys=True),
                    result.confidence,
                    result.workedAgainstCheckpoint,
                    result.agentContractVersion,
                    provider_used,
                    provider_type,
                    1 if provider_identity_verified else 0,
                    1 if provider_fallback_triggered else 0,
                    fallback_reason,
                    1 if synthetic else 0,
                ),
            )

    def insert_evidence_item(self, run_id: str, task_node_id: str, source_type: str, author_agent_id: str, content: str) -> None:
        self.conn.execute(
            """
            INSERT INTO evidence_items
                (id, run_id, task_node_id, source_type, author_agent_id, content, immutable)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (f"evidence-{uuid.uuid4().hex[:12]}", run_id, task_node_id, source_type, author_agent_id, content, 1),
        )

    def insert_artifact(self, run_id: str, task_node_id: str, name: str, path: str, artifact_type: str, author_agent_id: str) -> None:
        self.conn.execute(
            """
            INSERT INTO artifacts
                (id, run_id, task_node_id, name, path, type, author_agent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (f"artifact-{uuid.uuid4().hex[:12]}", run_id, task_node_id, name, path, artifact_type, author_agent_id),
        )

    def list_agent_results(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM agent_results
            WHERE run_id = ?
            ORDER BY rowid ASC
            """,
            (run_id,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "runId": row["run_id"],
                "taskNodeId": row["task_node_id"],
                "agentId": row["agent_id"],
                "status": row["status"],
                "summary": row["summary"],
                "evidence": json.loads(row["evidence_json"]),
                "artifacts": json.loads(row["artifacts_json"]),
                "risks": json.loads(row["risks_json"]),
                "nextActions": json.loads(row["next_actions_json"]),
                "confidence": row["confidence"],
                "workedAgainstCheckpoint": row["worked_against_checkpoint"],
                "agentContractVersion": row["agent_contract_version"],
                "providerUsed": row["provider_used"],
                "providerType": row["provider_type"],
                "providerIdentityVerified": bool(row["provider_identity_verified"]),
                "providerFallbackTriggered": bool(row["provider_fallback_triggered"]),
                "fallbackReason": row["fallback_reason"],
                "synthetic": bool(row["synthetic"]),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def list_evidence_items(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM evidence_items
            WHERE run_id = ?
            ORDER BY rowid ASC
            """,
            (run_id,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "runId": row["run_id"],
                "taskNodeId": row["task_node_id"],
                "sourceType": row["source_type"],
                "authorAgentId": row["author_agent_id"],
                "content": row["content"],
                "immutable": bool(row["immutable"]),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM artifacts
            WHERE run_id = ?
            ORDER BY rowid ASC
            """,
            (run_id,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "runId": row["run_id"],
                "taskNodeId": row["task_node_id"],
                "name": row["name"],
                "path": row["path"],
                "type": row["type"],
                "authorAgentId": row["author_agent_id"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    # --- Review Findings ---

    def insert_review_finding(
        self,
        finding_id: str,
        run_id: str,
        task_node_id: str,
        author_agent_id: str,
        severity: str,
        description: str,
        status: str = "active",
        superseded_by_id: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO review_findings
                (id, run_id, task_node_id, author_agent_id, severity, description, status, superseded_by_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (finding_id, run_id, task_node_id, author_agent_id, severity, description, status, superseded_by_id),
        )

    def insert_review_finding_history(self, finding_id: str, action: str, author_agent_id: str, payload: dict[str, Any]) -> str:
        history_id = f"finding-history-{uuid.uuid4().hex[:12]}"
        self.conn.execute(
            """
            INSERT INTO review_findings_history
                (id, finding_id, action, author_agent_id, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (history_id, finding_id, action, author_agent_id, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        )
        return history_id

    def get_review_finding(self, finding_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM review_findings WHERE id = ?", (finding_id,)).fetchone()
        return dict(row) if row else None

    def supersede_review_finding(self, finding_id: str, replacement_id: str) -> None:
        self.conn.execute(
            "UPDATE review_findings SET status = ?, superseded_by_id = ? WHERE id = ?",
            ("superseded", replacement_id, finding_id),
        )

    def list_review_findings(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM review_findings WHERE run_id = ? ORDER BY rowid ASC", (run_id,)).fetchall()
        return [
            {
                "id": row["id"],
                "runId": row["run_id"],
                "taskNodeId": row["task_node_id"],
                "authorAgentId": row["author_agent_id"],
                "severity": row["severity"],
                "description": row["description"],
                "status": row["status"],
                "supersededById": row["superseded_by_id"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def list_review_finding_history(self, finding_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM review_findings_history WHERE finding_id = ? ORDER BY rowid ASC", (finding_id,)).fetchall()
        return [
            {
                "id": row["id"],
                "findingId": row["finding_id"],
                "action": row["action"],
                "authorAgentId": row["author_agent_id"],
                "payload": json.loads(row["payload_json"]),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    # --- Directives ---

    def insert_directive(self, directive_id: str, run_id: str, source: str, message: str) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO user_directives (id, run_id, source, message)
                VALUES (?, ?, ?, ?)
                """,
                (directive_id, run_id, source, message),
            )
