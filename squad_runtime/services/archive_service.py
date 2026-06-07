"""Service for run archival and log export."""

from __future__ import annotations

import hashlib
import json
import locale
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

from ..event_store import EventStore
from ..models import TaskNode
from ..profile_registry import EvidenceScenarioType, ResolvedProfileLoader
from ..repositories.artifact_repository import ArtifactRepository
from ..repositories.gate_repository import GateRepository
from ..repositories.node_repository import NodeRepository
from ..repositories.run_repository import RunRepository
from ..schema_migration import SchemaMigrationEngine


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
        manifest = self._build_archive_manifest(run_id, payload)
        (archive_dir / "archive-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        (archive_dir / "README.md").write_text(self._render_archive_readme(manifest), encoding="utf-8")
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

    def _build_archive_manifest(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        events = payload["events"]
        profile = ResolvedProfileLoader.default().freeze(EvidenceScenarioType.REAL_ACCEPTANCE)
        return {
            "schemaVersion": "archive-manifest/v1",
            "runId": run_id,
            "gitCommit": self._git_commit(),
            "providerIdentity": self._provider_identity(payload["agentResults"]),
            "testSummary": {
                "agentResultCount": len(payload["agentResults"]),
                "gateCount": len(payload["gates"]),
                "passingGates": sum(1 for gate in payload["gates"] if gate["status"] == "pass"),
            },
            "frozenResolvedProfile": profile.to_dict(),
            "resolvedProfileHash": profile.resolved_profile_hash,
            "sourceProfiles": list(profile.source_profiles),
            "finalEventHash": self._last_event_payload(events, "event_hash_chain_sealed", "finalEventHash"),
            "environmentFingerprint": self._environment_fingerprint(),
            "providerAudit": self._provider_audit(payload["agentResults"]),
            "chainGraph": {
                "chainGraphHash": self._last_event_payload(events, "runtime_chain_graph_sealed", "chainGraphHash"),
                "chainBuilderVersion": self._last_event_payload(events, "runtime_chain_graph_sealed", "chainBuilderVersion"),
                "chainGraphSchemaVersion": "runtime-chain-graph/v1",
            },
            "failureRecords": self._failure_records(events),
            "artifactChecksums": self._artifact_checksums(payload["artifacts"]),
            "observability": {
                "providerLatencyMs": [event["payload"] for event in events if event["type"] == "provider_latency"],
                "rateLimitWaitEvents": sum(1 for event in events if event["type"] == "provider_rate_limit_wait"),
                "tokenCost": {"status": "placeholder", "tokensIn": None, "tokensOut": None, "costUsd": None},
                "toolDurations": [event["payload"] for event in events if event["type"] == "tool_call" and "durationMs" in event["payload"]],
                "failedToolCalls": [event["payload"] for event in events if event["type"] == "tool_permission_denied"],
            },
            "timeline": self._timeline(events),
            "environmentCompatibilityReport": {"status": "not_evaluated"},
            "schemaMigrationReport": SchemaMigrationEngine().validate_or_migrate(payload),
        }

    @staticmethod
    def _provider_identity(agent_results: list[dict[str, Any]]) -> dict[str, Any]:
        providers = sorted({result["providerUsed"] for result in agent_results})
        return {"providers": providers, "allIdentityVerified": all(result["providerIdentityVerified"] for result in agent_results)}

    @staticmethod
    def _provider_audit(agent_results: list[dict[str, Any]]) -> dict[str, Any]:
        providers: dict[str, dict[str, Any]] = {}
        for result in agent_results:
            provider = providers.setdefault(
                result["providerUsed"],
                {"identityVerified": True, "agentCount": 0, "systemPromptContentHash": None, "userPromptContentHash": None},
            )
            provider["identityVerified"] = bool(provider["identityVerified"] and result["providerIdentityVerified"])
            provider["agentCount"] = int(provider["agentCount"]) + 1
        return {"providers": providers}

    @staticmethod
    def _environment_fingerprint() -> dict[str, Any]:
        return {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "timezone": time.tzname[0] if time.tzname else "unknown",
            "locale": locale.getlocale()[0] or "unknown",
            "filesystemCaseSensitive": os.name != "nt",
        }

    @staticmethod
    def _git_commit() -> str:
        try:
            completed = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return "unknown"
        return completed.stdout.strip() or "unknown"

    @staticmethod
    def _last_event_payload(events: list[dict[str, Any]], event_type: str, key: str) -> Any:
        for event in reversed(events):
            if event["type"] == event_type:
                return event["payload"].get(key)
        return None

    @staticmethod
    def _failure_records(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        failure_events = {
            "invalid_agent_result",
            "tool_permission_denied",
            "checkpoint_mismatch",
            "provider_blocked",
            "provider_rate_limited",
            "agent_timeout",
        }
        return [
            {
                "eventType": event["type"],
                "failureClass": event["payload"].get("failureClass") or event["payload"].get("blockedReasonCode"),
                "severity": "blocking",
                "payload": event["payload"],
            }
            for event in events
            if event["type"] in failure_events
        ]

    def _artifact_checksums(self, artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        checksums = []
        for artifact in artifacts:
            path = Path(str(artifact["path"]))
            candidates = [path] if path.is_absolute() else [self._squad_dir.parent / path, self._squad_dir / "artifacts" / path]
            existing = next((candidate for candidate in candidates if candidate.exists() and candidate.is_file()), None)
            checksums.append(
                {
                    "artifactId": artifact["id"],
                    "path": artifact["path"],
                    "checksum": f"sha256:{hashlib.sha256(existing.read_bytes()).hexdigest()}" if existing else None,
                    "status": "present" if existing else "missing",
                }
            )
        return checksums

    @staticmethod
    def _timeline(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "sequenceNumber": event["sequence_number"],
                "type": event["type"],
                "createdAt": event["created_at"],
                "canonicalizationSpecificationVersion": "canonicalization/v1",
            }
            for event in events
        ]

    @staticmethod
    def _render_archive_readme(manifest: dict[str, Any]) -> str:
        return "\n".join(
            [
                "# Squad Runtime Archive",
                "",
                f"Run ID: `{manifest['runId']}`",
                f"Schema: `{manifest['schemaVersion']}`",
                f"Resolved Profile: `{manifest['resolvedProfileHash']}`",
                f"Final Event Hash: `{manifest['finalEventHash']}`",
                "",
            ]
        )
