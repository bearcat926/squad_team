from __future__ import annotations

import copy
from typing import Any

# Schema version constants
SCHEMA_V1 = "1.0"
SCHEMA_V2 = "2.0"
CANONICALIZATION_SPEC_V1 = "1.0"

_CONFIG_ERROR = "CONFIG_ERROR"

_HASH_FIELDS = {"previousEventHash", "eventPayloadHash", "eventHash"}


def _build_migration_report_v1_to_v2() -> dict[str, Any]:
    """Build the migration report for v1 -> v2 migration."""
    return {
        "schemaVersion": "1.0",
        "sourceSchemaVersion": SCHEMA_V1,
        "targetSchemaVersion": SCHEMA_V2,
        "sourceCanonicalizationSpecVersion": "unavailable-in-v1",
        "targetCanonicalizationSpecVersion": CANONICALIZATION_SPEC_V1,
        "eventHashChain": "unavailable-in-v1",
        "tamperDetection": "not-available-for-historical-events",
        "allowedModes": ["re-evaluation", "state-reconstruction-with-warning"],
        "disallowedModes": ["tamper-proof replay"],
        "warnings": [
            {
                "code": "EVENT_HASH_CHAIN_UNAVAILABLE_IN_V1",
                "message": "Historical archive does not contain previousEventHash/eventPayloadHash/eventHash. Hash chain must not be fabricated.",
            }
        ],
    }


def _strip_fabricated_hashes(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove any hash fields that might have been added during migration.

    The canonicalization freeze rule: we must NEVER fabricate hash chain values
    for historical archives that did not originally contain them.
    """
    cleaned: list[dict[str, Any]] = []
    for event in events:
        cleaned_event = {k: v for k, v in event.items() if k not in _HASH_FIELDS}
        cleaned.append(cleaned_event)
    return cleaned


def migrate_v1_to_v2(payload: dict[str, Any]) -> dict[str, Any]:
    """Migrate a v1 runtime log archive to v2 format.

    Key invariants:
    - schemaVersion is updated to "2.0"
    - A migrationReport is added documenting what changed
    - Event hash chain fields are NEVER fabricated (canonicalization freeze rule)
    - Original data (run, nodes, events, agentResults, gates) is preserved as-is
    """
    migrated = copy.deepcopy(payload)
    migrated["schemaVersion"] = SCHEMA_V2
    migrated["migrationReport"] = _build_migration_report_v1_to_v2()

    # Canonicalization freeze: strip any hash fields that shouldn't be there
    if "events" in migrated:
        migrated["events"] = _strip_fabricated_hashes(migrated["events"])

    return migrated


class SchemaMigrationEngine:
    """Validates replay payload schema versions and applies migrations.

    Handles runtime log archive schema evolution. Supports:
    - v1.0 -> v2.0 migration with migrationReport generation
    - Canonicalization freeze: never fabricate event hashes for historical archives
    - CONFIG_ERROR for unknown/unrecognized schema versions
    """

    def validate_or_migrate(self, payload: dict[str, Any]) -> dict[str, Any]:
        version = payload.get("schemaVersion") or payload.get("run", {}).get("schemaVersion") or payload.get("run", {}).get("schema_version")

        if version in {"v1", "runtime-log/v1", SCHEMA_V1}:
            # Check if this is a top-level schemaVersion (runtime log archive)
            if "schemaVersion" in payload and payload["schemaVersion"] == SCHEMA_V1:
                return migrate_v1_to_v2(payload)

            # Legacy: embedded schema version in run object
            return {
                "schemaVersion": "schema-migration-report/v1",
                "status": "compatible",
                "fromVersion": version,
                "toVersion": version,
                "appliedMigrations": [],
                "failureClass": None,
            }

        if version == SCHEMA_V2:
            # Already v2, return as-is
            return payload

        return {
            "schemaVersion": "schema-migration-report/v1",
            "status": "failed",
            "fromVersion": version,
            "toVersion": None,
            "appliedMigrations": [],
            "failureClass": _CONFIG_ERROR,
        }
