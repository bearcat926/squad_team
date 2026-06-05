"""Service for run archival and log export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..event_store import EventStore
from ..models import TaskNode
from ..repositories.artifact_repository import ArtifactRepository
from ..repositories.gate_repository import GateRepository
from ..repositories.node_repository import NodeRepository
from ..repositories.run_repository import RunRepository


class ArchiveService:
    """Business logic for archiving and exporting run data."""

    def __init__(
        self,
        run_repo: RunRepository,
        node_repo: NodeRepository,
        gate_repo: GateRepository,
        artifact_repo: ArtifactRepository,
        events: EventStore,
        squad_dir: Path,
    ):
        self._run_repo = run_repo
        self._node_repo = node_repo
        self._gate_repo = gate_repo
        self._artifact_repo = artifact_repo
        self._events = events
        self._squad_dir = squad_dir

    def archive_run(self, run_id: str) -> Path:
        run = self._run_repo.get(run_id)
        archive_dir = self._squad_dir / "runs" / run_id
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / "archive.json"
        payload = {
            "run": run.__dict__,
            "nodes": [self._node_to_dict(node) for node in self._node_repo.list_by_run(run_id)],
            "gates": self._gate_repo.list_by_run(run_id),
            "agentResults": self._artifact_repo.list_agent_results(run_id),
            "evidenceItems": self._artifact_repo.list_evidence_items(run_id),
            "reviewFindings": self._artifact_repo.list_review_findings(run_id),
            "artifacts": self._artifact_repo.list_artifacts(run_id),
            "events": [event.__dict__ for event in self._events.query(run_id, limit=10000).events],
        }
        archive_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        self._events.append(run_id, "run_archived", {"archivePath": str(archive_path)}, critical=True)
        return archive_path

    def export_run_log(self, run_id: str, output_path: Path, include_export_event: bool = False) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if include_export_event:
            self._events.append(run_id, "log_exported", {"outputPath": str(output_path), "final": True}, critical=True)
        run = self._run_repo.get(run_id)
        events = [event.__dict__ for event in self._events.query(run_id, limit=100000).events]
        payload = {
            "run": run.__dict__,
            "nodes": [self._node_to_dict(node) for node in self._node_repo.list_by_run(run_id)],
            "gates": self._gate_repo.list_by_run(run_id),
            "agentResults": self._artifact_repo.list_agent_results(run_id),
            "evidenceItems": self._artifact_repo.list_evidence_items(run_id),
            "reviewFindings": self._artifact_repo.list_review_findings(run_id),
            "artifacts": self._artifact_repo.list_artifacts(run_id),
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
            self._events.append(run_id, "log_exported", {"outputPath": str(output_path)}, critical=True)
        return output_path

    @staticmethod
    def _render_full_data_log_markdown(payload: dict[str, Any]) -> str:
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

    @staticmethod
    def _node_to_dict(node: TaskNode) -> dict[str, Any]:
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
