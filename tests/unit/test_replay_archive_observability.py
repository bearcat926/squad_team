from __future__ import annotations

import json
from pathlib import Path

from squad_runtime.agent_contracts import AgentResult
from squad_runtime.replay import ReplayEngine
from squad_runtime.runtime import Runtime
from squad_runtime.schema_migration import SchemaMigrationEngine


def add_result(runtime: Runtime, run_id: str) -> None:
    node = runtime.create_node(run_id, "Test", "test", "test-engineer", checkpoint_id="ckp")
    runtime.persist_agent_result(
        AgentResult(
            taskNodeId=node.id,
            agentId="test-engineer",
            status="pass",
            summary="tests pass",
            evidence=[],
            artifacts=[],
            risks=[],
            nextActions=[],
            confidence=0.9,
            workedAgainstCheckpoint="ckp",
            agentContractVersion="v1",
        ),
        provider_used="claude_cli",
        provider_type="real_llm",
        provider_identity_verified=True,
    )


def test_archive_manifest_contains_replay_observability_metadata(tmp_path: Path) -> None:
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("archive")
    add_result(runtime, run.id)
    runtime.upsert_gate_state(run.id, "test_gate", "pass", "ok")
    runtime.record_event(run.id, "provider_latency", {"agentId": "test-engineer", "latencyMs": 1200})
    runtime.record_event(run.id, "provider_rate_limit_wait", {"provider": "claude_cli", "waitSeconds": 30})
    runtime.record_event(run.id, "event_hash_chain_sealed", {"finalEventHash": "sha256:event"})
    runtime.record_event(run.id, "runtime_chain_graph_sealed", {"chainGraphHash": "sha256:chain", "chainBuilderVersion": "chain-builder/v1"})

    archive_path = runtime.archive_run(run.id)
    archive_dir = archive_path.parent
    manifest = json.loads((archive_dir / "archive-manifest.json").read_text(encoding="utf-8"))

    assert manifest["schemaVersion"] == "archive-manifest/v1"
    assert manifest["runId"] == run.id
    assert manifest["gitCommit"]
    assert manifest["resolvedProfileHash"].startswith("sha256:")
    assert manifest["finalEventHash"] == "sha256:event"
    assert manifest["environmentFingerprint"]["timezone"]
    assert "filesystemCaseSensitive" in manifest["environmentFingerprint"]
    assert manifest["providerAudit"]["providers"]["claude_cli"]["identityVerified"] is True
    assert manifest["chainGraph"]["chainGraphHash"] == "sha256:chain"
    assert manifest["observability"]["rateLimitWaitEvents"] == 1
    assert manifest["observability"]["tokenCost"]["status"] == "placeholder"
    assert manifest["timeline"][0]["canonicalizationSpecificationVersion"] == "canonicalization/v1"
    assert (archive_dir / "README.md").exists()


def test_replay_engine_reconstructs_state_from_full_data_log(tmp_path: Path) -> None:
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("replay")
    add_result(runtime, run.id)
    runtime.upsert_gate_state(run.id, "test_gate", "pass", "ok")
    log_path = tmp_path / "FULL_DATA_LOG.json"
    runtime.export_run_log(run.id, log_path, include_export_event=True)

    state = ReplayEngine().reconstruct_state(log_path)

    assert state["schemaVersion"] == "reconstructed-state/v1"
    assert state["run"]["id"] == run.id
    assert state["agentResults"]["test-engineer"] == "pass"
    assert state["gates"]["test_gate"] == "pass"
    assert state["eventCount"] >= 1


def test_schema_migration_engine_reports_v1_compatible_payload() -> None:
    report = SchemaMigrationEngine().validate_or_migrate({"run": {"schema_version": "v1"}})

    assert report["schemaVersion"] == "schema-migration-report/v1"
    assert report["status"] == "compatible"
    assert report["fromVersion"] == "v1"
    assert report["failureClass"] is None
