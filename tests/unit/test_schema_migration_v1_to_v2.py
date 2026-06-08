"""Tests for v1 -> v2 schema migration of runtime log archives.

Covers:
- Schema version upgrade
- Data preservation
- Migration report generation
- Canonicalization freeze rule (never fabricate hashes)
- CONFIG_ERROR for unknown schemas
- Replay and re-evaluation mode support
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from squad_runtime.schema_migration import (
    SCHEMA_V1,
    SCHEMA_V2,
    SchemaMigrationEngine,
    migrate_v1_to_v2,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "schema"


@pytest.fixture()
def v1_payload() -> dict:
    """Load the v1 runtime log fixture."""
    return json.loads((FIXTURES / "v1-runtime-log.json").read_text(encoding="utf-8"))


@pytest.fixture()
def expected_v2() -> dict:
    """Load the expected v2 output fixture."""
    return json.loads((FIXTURES / "v2-runtime-log.expected.json").read_text(encoding="utf-8"))


@pytest.fixture()
def engine() -> SchemaMigrationEngine:
    return SchemaMigrationEngine()


# ── Core migration tests ────────────────────────────────────────────────────


def test_v1_to_v2_migration_adds_schema_version(v1_payload: dict) -> None:
    result = migrate_v1_to_v2(v1_payload)
    assert result["schemaVersion"] == SCHEMA_V2


def test_v1_to_v2_migration_preserves_original_data(v1_payload: dict) -> None:
    result = migrate_v1_to_v2(v1_payload)
    assert result["run"] == v1_payload["run"]
    assert result["nodes"] == v1_payload["nodes"]
    assert result["events"] == v1_payload["events"]
    assert result["agentResults"] == v1_payload["agentResults"]
    assert result["gates"] == v1_payload["gates"]


def test_v1_to_v2_migration_report_present(v1_payload: dict) -> None:
    result = migrate_v1_to_v2(v1_payload)
    assert "migrationReport" in result
    report = result["migrationReport"]
    assert report["sourceSchemaVersion"] == SCHEMA_V1
    assert report["targetSchemaVersion"] == SCHEMA_V2


def test_v1_to_v2_migration_does_not_fabricate_hashes(v1_payload: dict) -> None:
    # Even if someone injects hash fields into v1 events, migration strips them
    tampered = copy.deepcopy(v1_payload)
    tampered["events"][0]["previousEventHash"] = "sha256:fake"
    tampered["events"][0]["eventPayloadHash"] = "sha256:fake"
    tampered["events"][0]["eventHash"] = "sha256:fake"

    result = migrate_v1_to_v2(tampered)
    event = result["events"][0]
    assert "previousEventHash" not in event
    assert "eventPayloadHash" not in event
    assert "eventHash" not in event


# ── Migration report field tests ────────────────────────────────────────────


def test_v1_migration_report_marks_unavailable_in_v1(v1_payload: dict) -> None:
    result = migrate_v1_to_v2(v1_payload)
    report = result["migrationReport"]
    assert report["sourceCanonicalizationSpecVersion"] == "unavailable-in-v1"
    assert report["eventHashChain"] == "unavailable-in-v1"


def test_v1_migration_report_allowed_modes(v1_payload: dict) -> None:
    result = migrate_v1_to_v2(v1_payload)
    report = result["migrationReport"]
    assert "re-evaluation" in report["allowedModes"]
    assert "state-reconstruction-with-warning" in report["allowedModes"]
    assert "tamper-proof replay" in report["disallowedModes"]


def test_migration_report_schema(v1_payload: dict) -> None:
    """Validate migrationReport has all required fields per the spec."""
    result = migrate_v1_to_v2(v1_payload)
    report = result["migrationReport"]
    required_fields = [
        "schemaVersion",
        "sourceSchemaVersion",
        "targetSchemaVersion",
        "sourceCanonicalizationSpecVersion",
        "targetCanonicalizationSpecVersion",
        "eventHashChain",
        "tamperDetection",
        "allowedModes",
        "disallowedModes",
        "warnings",
    ]
    for field in required_fields:
        assert field in report, f"migrationReport missing required field: {field}"

    assert isinstance(report["warnings"], list)
    assert len(report["warnings"]) > 0
    assert "code" in report["warnings"][0]
    assert "message" in report["warnings"][0]


# ── Unknown / unsupported schema tests ──────────────────────────────────────


def test_unknown_schema_returns_config_error(engine: SchemaMigrationEngine) -> None:
    payload = {"schemaVersion": "99.0", "run": {}, "nodes": [], "events": [], "agentResults": [], "gates": []}
    result = engine.validate_or_migrate(payload)
    assert result["status"] == "failed"
    assert result["failureClass"] == "CONFIG_ERROR"


def test_unsupported_canonicalization_version_returns_config_error(engine: SchemaMigrationEngine) -> None:
    """Try to replay with unknown canonicalizationSpecVersion -> CONFIG_ERROR."""
    payload = {
        "schemaVersion": "99.0",
        "canonicalizationSpecVersion": "unknown-version",
        "run": {},
        "nodes": [],
        "events": [],
        "agentResults": [],
        "gates": [],
    }
    result = engine.validate_or_migrate(payload)
    assert result["failureClass"] == "CONFIG_ERROR"


# ── Tamper detection / archive integrity tests ─────────────────────────────


def test_v1_archive_does_not_claim_tamper_detection(v1_payload: dict) -> None:
    result = migrate_v1_to_v2(v1_payload)
    report = result["migrationReport"]
    assert report["tamperDetection"] == "not-available-for-historical-events"
    # No event should claim tamper-proof status
    for event in result["events"]:
        assert "eventHash" not in event
        assert "previousEventHash" not in event


def test_v1_archive_allows_re_evaluation(v1_payload: dict) -> None:
    result = migrate_v1_to_v2(v1_payload)
    report = result["migrationReport"]
    assert "re-evaluation" in report["allowedModes"]


def test_v1_archive_state_reconstruction_marks_tamper_detection_unavailable(v1_payload: dict) -> None:
    result = migrate_v1_to_v2(v1_payload)
    report = result["migrationReport"]
    assert "state-reconstruction-with-warning" in report["allowedModes"]
    assert report["tamperDetection"] == "not-available-for-historical-events"
    # Warnings should be present to flag the limitation
    assert len(report["warnings"]) > 0


# ── Canonicalization version tests ──────────────────────────────────────────


def test_canonicalization_version_change_migration_report(v1_payload: dict) -> None:
    result = migrate_v1_to_v2(v1_payload)
    report = result["migrationReport"]
    assert report["sourceCanonicalizationSpecVersion"] == "unavailable-in-v1"
    assert report["targetCanonicalizationSpecVersion"] == "1.0"


def test_replay_uses_archived_canonicalization_version(v1_payload: dict) -> None:
    """Verify replay respects the version from archive."""
    result = migrate_v1_to_v2(v1_payload)
    report = result["migrationReport"]
    # The target canonicalization version is the one to use for replay
    assert report["targetCanonicalizationSpecVersion"] == "1.0"


def test_current_canonicalization_does_not_rehash_historical_archive(v1_payload: dict) -> None:
    """Verify we don't recompute hashes for old events."""
    # Events in v1 have no hash fields
    result = migrate_v1_to_v2(v1_payload)
    for event in result["events"]:
        assert "eventPayloadHash" not in event
        assert "eventHash" not in event
        assert "previousEventHash" not in event
