from __future__ import annotations

import sqlite3
import uuid
import json
from pathlib import Path
from typing import Any

from .agent_contracts import AgentResult, validate_agent_result
from .event_store import EventStore
from .models import SquadRun, TaskNode
from .state import BLOCKED_REASON_CODES, InvalidTransition, NodeStatus, ensure_transition_allowed


class Runtime:
    def __init__(self, squad_dir: Path):
        self.squad_dir = Path(squad_dir)
        self.squad_dir.mkdir(parents=True, exist_ok=True)
        (self.squad_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.squad_dir / "checkpoints").mkdir(parents=True, exist_ok=True)
        (self.squad_dir / "runs").mkdir(parents=True, exist_ok=True)
        (self.squad_dir / "rules").mkdir(parents=True, exist_ok=True)
        self.db_path = self.squad_dir / "squad.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.events = EventStore(self.squad_dir)
        self._init_schema()

    @classmethod
    def create(cls, squad_dir: Path) -> "Runtime":
        return cls(squad_dir)

    def create_run(
        self,
        goal: str,
        rule_version: str = "v1",
        schema_version: str = "v1",
        agent_contract_version: str = "v1",
    ) -> SquadRun:
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO squad_runs
                    (id, goal, status, version, rule_version, schema_version, agent_contract_version)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, goal, "planning", 0, rule_version, schema_version, agent_contract_version),
            )
        self.events.append(run_id, "run_created", {"goal": goal}, critical=True)
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> SquadRun:
        row = self.conn.execute("SELECT * FROM squad_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return SquadRun(
            id=row["id"],
            goal=row["goal"],
            status=row["status"],
            version=int(row["version"]),
            rule_version=row["rule_version"],
            schema_version=row["schema_version"],
            agent_contract_version=row["agent_contract_version"],
        )

    def list_runs(self) -> list[SquadRun]:
        rows = self.conn.execute("SELECT * FROM squad_runs ORDER BY rowid ASC").fetchall()
        return [
            SquadRun(
                id=row["id"],
                goal=row["goal"],
                status=row["status"],
                version=int(row["version"]),
                rule_version=row["rule_version"],
                schema_version=row["schema_version"],
                agent_contract_version=row["agent_contract_version"],
            )
            for row in rows
        ]

    def create_node(self, run_id: str, title: str, node_type: str, owner_agent_id: str, checkpoint_id: str = "ckp-1") -> TaskNode:
        node_id = f"node-{uuid.uuid4().hex[:12]}"
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO task_nodes
                    (id, run_id, title, type, owner_agent_id, status, blocked_reason_code, checkpoint_id, replaced_by_node_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (node_id, run_id, title, node_type, owner_agent_id, NodeStatus.TODO.value, None, checkpoint_id, None),
            )
        self.events.append(run_id, "node_created", {"nodeId": node_id, "type": node_type}, critical=True)
        return self.get_node(node_id)

    def get_node(self, node_id: str) -> TaskNode:
        row = self.conn.execute("SELECT * FROM task_nodes WHERE id = ?", (node_id,)).fetchone()
        if row is None:
            raise KeyError(node_id)
        return self._row_to_node(row)

    def list_nodes(self, run_id: str) -> list[TaskNode]:
        rows = self.conn.execute("SELECT * FROM task_nodes WHERE run_id = ? ORDER BY rowid ASC", (run_id,)).fetchall()
        return [self._row_to_node(row) for row in rows]

    def transition_node(
        self,
        node_id: str,
        from_status: NodeStatus,
        to_status: NodeStatus,
        reason: str,
        blocked_reason_code: str | None = None,
        metadata: dict[str, Any] | None = None,
        expected_run_version: int | None = None,
    ) -> TaskNode:
        if to_status == NodeStatus.BLOCKED and not blocked_reason_code:
            raise ValueError("blockedReasonCode is required when node status becomes blocked")
        if blocked_reason_code and blocked_reason_code not in BLOCKED_REASON_CODES:
            raise ValueError(f"Unknown blockedReasonCode: {blocked_reason_code}")
        ensure_transition_allowed(from_status, to_status)
        node = self.get_node(node_id)
        run = self.get_run(node.run_id)
        if expected_run_version is not None and run.version != expected_run_version:
            self.events.append(
                node.run_id,
                "transition_conflict",
                {
                    "nodeId": node_id,
                    "expectedRunVersion": expected_run_version,
                    "actualRunVersion": run.version,
                    "to": to_status.value,
                },
                critical=True,
            )
            raise InvalidTransition(f"Expected run version {expected_run_version}, got {run.version}")
        if node.status != from_status:
            self.events.append(
                node.run_id,
                "transition_conflict",
                {"nodeId": node_id, "expected": from_status.value, "actual": node.status.value, "to": to_status.value},
                critical=True,
            )
            raise InvalidTransition(f"Expected {from_status.value}, got {node.status.value}")

        with self.conn:
            self.conn.execute(
                """
                UPDATE task_nodes
                SET status = ?, blocked_reason_code = ?
                WHERE id = ? AND status = ?
                """,
                (to_status.value, blocked_reason_code, node_id, from_status.value),
            )
            self.conn.execute("UPDATE squad_runs SET version = version + 1 WHERE id = ?", (node.run_id,))
        self.events.append(
            node.run_id,
            "node_status_changed",
            {
                "nodeId": node_id,
                "from": from_status.value,
                "to": to_status.value,
                "reason": reason,
                "blockedReasonCode": blocked_reason_code,
                "metadata": metadata or {},
            },
            critical=True,
        )
        return self.get_node(node_id)

    def apply_agent_result(self, result: AgentResult) -> str:
        node = self.get_node(result.taskNodeId)
        if node.status in {NodeStatus.CANCELED, NodeStatus.STALE, NodeStatus.DONE}:
            self.events.append(node.run_id, "stale_advisory", {"nodeId": node.id, "agentId": result.agentId}, critical=True)
            return "stale_advisory"

        validation = validate_agent_result(result, self.squad_dir / "artifacts", node.checkpoint_id)
        if not validation.valid:
            self.transition_node(
                node.id,
                node.status,
                NodeStatus.BLOCKED,
                "invalid agent result",
                blocked_reason_code="invalid_agent_result",
                metadata={"errors": validation.errors},
            )
            self.events.append(node.run_id, "invalid_agent_result", {"nodeId": node.id, "errors": validation.errors}, critical=True)
            return "invalid_agent_result"

        target = NodeStatus(result.status)
        if node.status != NodeStatus.RUNNING:
            self.events.append(
                node.run_id,
                "stale_advisory",
                {"nodeId": node.id, "agentId": result.agentId, "actualStatus": node.status.value},
                critical=True,
            )
            return "stale_advisory"
        self.transition_node(
            node.id,
            NodeStatus.RUNNING,
            target,
            "agent result",
            blocked_reason_code="gate_dependency_failed" if target == NodeStatus.BLOCKED else None,
        )
        return result.status


    def persist_agent_result(
        self,
        result: AgentResult,
        provider_used: str,
        provider_type: str = "deterministic",
        provider_identity_verified: bool = False,
        provider_fallback_triggered: bool = False,
        fallback_reason: str | None = None,
        synthetic: bool = False,
    ) -> str:
        node = self.get_node(result.taskNodeId)
        validation = validate_agent_result(result, self.squad_dir / "artifacts", node.checkpoint_id)
        if not validation.valid:
            self.events.append(
                node.run_id,
                "invalid_agent_result",
                {"nodeId": node.id, "agentId": result.agentId, "errors": validation.errors},
                critical=True,
            )
            return "invalid_agent_result"
        result_id = f"agent-result-{uuid.uuid4().hex[:12]}"
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
                    node.run_id,
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
            for evidence in result.evidence:
                self.conn.execute(
                    """
                    INSERT INTO evidence_items
                        (id, run_id, task_node_id, source_type, author_agent_id, content, immutable)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"evidence-{uuid.uuid4().hex[:12]}",
                        node.run_id,
                        result.taskNodeId,
                        evidence.get("type", "agent"),
                        result.agentId,
                        evidence.get("content", ""),
                        1,
                    ),
                )
            for artifact in result.artifacts:
                self.conn.execute(
                    """
                    INSERT INTO artifacts
                        (id, run_id, task_node_id, name, path, type, author_agent_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"artifact-{uuid.uuid4().hex[:12]}",
                        node.run_id,
                        result.taskNodeId,
                        artifact.get("name", "artifact"),
                        artifact.get("path", ""),
                        artifact.get("type", "agent-artifact"),
                        result.agentId,
                    ),
                )
        self.events.append(
            node.run_id,
            "agent_result_submitted",
            {
                "agentResultId": result_id,
                "taskNodeId": result.taskNodeId,
                "agentId": result.agentId,
                "status": result.status,
                "providerUsed": provider_used,
                "providerFallbackTriggered": provider_fallback_triggered,
                "fallbackReason": fallback_reason,
                "synthetic": synthetic,
            },
            critical=True,
        )
        return result_id

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

    def recover_running_dispatches(self) -> list[TaskNode]:
        recovered: list[TaskNode] = []
        rows = self.conn.execute("SELECT id FROM task_nodes WHERE status = ?", (NodeStatus.RUNNING.value,)).fetchall()
        for row in rows:
            node = self.get_node(row["id"])
            updated = self.transition_node(node.id, NodeStatus.RUNNING, NodeStatus.AGENT_UNAVAILABLE, "server restart")
            self.events.append(
                updated.run_id,
                "server_restart_dispatch_recovery",
                {"nodeId": updated.id, "ownerAgentId": updated.owner_agent_id},
                critical=True,
            )
            recovered.append(updated)
        return recovered


    def create_review_finding(
        self,
        run_id: str,
        task_node_id: str,
        author_agent_id: str,
        severity: str,
        description: str,
    ) -> str:
        if author_agent_id != "code-reviewer":
            raise PermissionError("Only code-reviewer may create review findings")
        finding_id = f"finding-{uuid.uuid4().hex[:12]}"
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO review_findings
                    (id, run_id, task_node_id, author_agent_id, severity, description, status, superseded_by_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (finding_id, run_id, task_node_id, author_agent_id, severity, description, "active", None),
            )
            self.conn.execute(
                """
                INSERT INTO review_findings_history
                    (id, finding_id, action, author_agent_id, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    f"finding-history-{uuid.uuid4().hex[:12]}",
                    finding_id,
                    "created",
                    author_agent_id,
                    json.dumps({"severity": severity, "description": description}, ensure_ascii=False, sort_keys=True),
                ),
            )
        return finding_id

    def supersede_review_finding(
        self,
        finding_id: str,
        author_agent_id: str,
        severity: str,
        description: str,
    ) -> str:
        if author_agent_id != "code-reviewer":
            raise PermissionError("Only code-reviewer may supersede review findings")
        row = self.conn.execute("SELECT * FROM review_findings WHERE id = ?", (finding_id,)).fetchone()
        if row is None:
            raise KeyError(finding_id)
        replacement_id = f"finding-{uuid.uuid4().hex[:12]}"
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO review_findings
                    (id, run_id, task_node_id, author_agent_id, severity, description, status, superseded_by_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (replacement_id, row["run_id"], row["task_node_id"], author_agent_id, severity, description, "active", None),
            )
            self.conn.execute(
                "UPDATE review_findings SET status = ?, superseded_by_id = ? WHERE id = ?",
                ("superseded", replacement_id, finding_id),
            )
            self.conn.execute(
                """
                INSERT INTO review_findings_history
                    (id, finding_id, action, author_agent_id, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    f"finding-history-{uuid.uuid4().hex[:12]}",
                    finding_id,
                    "superseded",
                    author_agent_id,
                    json.dumps({"replacementId": replacement_id, "severity": severity, "description": description}, ensure_ascii=False, sort_keys=True),
                ),
            )
        return replacement_id

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

    def record_directive(self, run_id: str, message: str, source: str = "user") -> str:
        directive_id = f"directive-{uuid.uuid4().hex[:12]}"
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO user_directives (id, run_id, source, message)
                VALUES (?, ?, ?, ?)
                """,
                (directive_id, run_id, source, message),
            )
        self.events.append(
            run_id,
            "directive_recorded",
            {"directiveId": directive_id, "source": source, "message": message},
            critical=True,
        )
        return directive_id

    def upsert_gate_state(self, run_id: str, gate_name: str, status: str, reason: str, blocked_reason_code: str | None = None) -> None:
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
        self.events.append(
            run_id,
            "gate_status_changed",
            {"gateName": gate_name, "status": status, "reason": reason, "blockedReasonCode": blocked_reason_code},
            critical=True,
        )

    def list_gate_states(self, run_id: str) -> list[dict[str, Any]]:
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

    def archive_run(self, run_id: str) -> Path:
        run = self.get_run(run_id)
        archive_dir = self.squad_dir / "runs" / run_id
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / "archive.json"
        payload = {
            "run": run.__dict__,
            "nodes": [self._node_to_dict(node) for node in self.list_nodes(run_id)],
            "gates": self.list_gate_states(run_id),
            "agentResults": self.list_agent_results(run_id),
            "evidenceItems": self.list_evidence_items(run_id),
            "reviewFindings": self.list_review_findings(run_id),
            "artifacts": self.list_artifacts(run_id),
            "events": [event.__dict__ for event in self.events.query(run_id, limit=10000).events],
        }
        archive_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        self.events.append(run_id, "run_archived", {"archivePath": str(archive_path)}, critical=True)
        return archive_path

    def close(self) -> None:
        self.events.close()
        self.conn.close()

    def __enter__(self) -> "Runtime":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


    def record_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_typed_event(event_type, payload)
        event = self.events.append(run_id, event_type, payload, critical=True)
        return {
            "id": event.id,
            "runId": event.run_id,
            "sequenceNumber": event.sequence_number,
            "type": event.type,
            "payload": event.payload,
            "critical": event.critical,
            "createdAt": event.created_at,
        }


    def _validate_typed_event(self, event_type: str, payload: dict[str, Any]) -> None:
        required = {
            "llm_session_started": {"dispatchId", "agentId"},
            "llm_session_completed": {"dispatchId", "agentId"},
            "agent_result_submitted": {"taskNodeId", "agentId", "status"},
            "tool_permission_denied": {"nodeId", "agentId", "path", "reason"},
            "gate_decision": {"gateName", "status", "reason"},
            "artifact_produced": {"name", "path", "type"},
            "provider_fallback_triggered": {"nodeId", "agentId", "primaryProvider", "fallbackProvider", "reason"},
        }.get(event_type)
        if required is None:
            return
        missing = sorted(required - payload.keys())
        if missing:
            raise ValueError(f"{event_type} missing required fields: {', '.join(missing)}")

    def record_artifact(self, run_id: str, name: str, path: str, artifact_type: str) -> dict[str, Any]:
        return self.record_event(
            run_id,
            "artifact_produced",
            {
                "name": name,
                "path": path,
                "type": artifact_type,
            },
        )

    def export_run_log(self, run_id: str, output_path: Path, include_export_event: bool = False) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if include_export_event:
            self.events.append(run_id, "log_exported", {"outputPath": str(output_path), "final": True}, critical=True)
        run = self.get_run(run_id)
        events = [event.__dict__ for event in self.events.query(run_id, limit=100000).events]
        payload = {
            "run": run.__dict__,
            "nodes": [self._node_to_dict(node) for node in self.list_nodes(run_id)],
            "gates": self.list_gate_states(run_id),
            "agentResults": self.list_agent_results(run_id),
            "evidenceItems": self.list_evidence_items(run_id),
            "reviewFindings": self.list_review_findings(run_id),
            "artifacts": self.list_artifacts(run_id),
            "events": events,
            "agentOperations": [event for event in events if event["type"] == "agent_operation"],
            "agentMessages": [event for event in events if event["type"] == "agent_message"],
            "dataFlows": [event for event in events if event["type"] == "data_flow"],
            "artifactEvents": [event for event in events if event["type"] == "artifact_produced"],
            "coverageLanes": [event for event in events if event["type"] == "coverage_lane_update"],
            "skillUsage": [event for event in events if event["type"] == "skill_usage"],
            "verificationResults": [event for event in events if event["type"] == "verification_result"],
        }
        if output_path.suffix.lower() == ".md":
            output_path.write_text(self._render_full_data_log_markdown(payload), encoding="utf-8")
        else:
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        if not include_export_event:
            self.events.append(run_id, "log_exported", {"outputPath": str(output_path)}, critical=True)
        return output_path

    def _render_full_data_log_markdown(self, payload: dict[str, Any]) -> str:
        lines: list[str] = ["# Squad Runtime Full Data Log", ""]
        lines.append("## Run Metadata")
        lines.append("```json")
        lines.append(json.dumps(payload["run"], ensure_ascii=False, indent=2, sort_keys=True))
        lines.append("```")
        lines.append("")
        for title, key in [
            ("Nodes", "nodes"),
            ("Gates", "gates"),
            ("Agent Results", "agentResults"),
            ("Evidence Items", "evidenceItems"),
            ("Review Findings", "reviewFindings"),
            ("Agent Operations", "agentOperations"),
            ("Agent Messages", "agentMessages"),
            ("Data Flows", "dataFlows"),
            ("Artifacts", "artifacts"),
            ("Artifact Events", "artifactEvents"),
            ("Coverage Lanes", "coverageLanes"),
            ("Skill Usage", "skillUsage"),
            ("Verification Results", "verificationResults"),
            ("All Events", "events"),
        ]:
            lines.append(f"## {title}")
            lines.append("```json")
            lines.append(json.dumps(payload[key], ensure_ascii=False, indent=2, sort_keys=True))
            lines.append("```")
            lines.append("")
        return "\n".join(lines)
    def _init_schema(self) -> None:
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS squad_runs (
                    id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    rule_version TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    agent_contract_version TEXT NOT NULL
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_directives (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    message TEXT NOT NULL
                )
                """
            )
            self.conn.execute(
                """
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
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gate_states (
                    run_id TEXT NOT NULL,
                    gate_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    blocked_reason_code TEXT,
                    reason TEXT NOT NULL,
                    PRIMARY KEY (run_id, gate_name)
                )
                """
            )

            self.conn.execute(
                """
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
                """
            )
            self.conn.execute(
                """
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
                """
            )
            self.conn.execute(
                """
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
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS review_findings_history (
                    id TEXT PRIMARY KEY,
                    finding_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    author_agent_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self.conn.execute(
                """
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
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dispatches (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    task_node_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS context_bundles (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    task_node_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            for column_name, column_sql in [
                ("provider_type", "ALTER TABLE agent_results ADD COLUMN provider_type TEXT NOT NULL DEFAULT 'deterministic'"),
                ("provider_identity_verified", "ALTER TABLE agent_results ADD COLUMN provider_identity_verified INTEGER NOT NULL DEFAULT 0"),
            ]:
                existing = [row[1] for row in self.conn.execute("PRAGMA table_info(agent_results)").fetchall()]
                if column_name not in existing:
                    self.conn.execute(column_sql)
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_health (
                    provider TEXT PRIMARY KEY,
                    available INTEGER NOT NULL,
                    detail TEXT NOT NULL,
                    checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _row_to_node(self, row: sqlite3.Row) -> TaskNode:
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

    def _node_to_dict(self, node: TaskNode) -> dict[str, Any]:
        return {
            "id": node.id,
            "runId": node.run_id,
            "title": node.title,
            "type": node.type,
            "ownerAgentId": node.owner_agent_id,
            "status": node.status.value,
            "blockedReasonCode": node.blocked_reason_code,
            "checkpointId": node.checkpoint_id,
            "replacedByNodeId": node.replaced_by_node_id,
        }

