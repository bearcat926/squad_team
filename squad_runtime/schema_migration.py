from __future__ import annotations

from typing import Any


class SchemaMigrationEngine:
    """Validates replay payload schema versions and reports migration decisions."""

    def validate_or_migrate(self, payload: dict[str, Any]) -> dict[str, Any]:
        version = payload.get("run", {}).get("schemaVersion") or payload.get("run", {}).get("schema_version")
        if version in {"v1", "runtime-log/v1"}:
            return {
                "schemaVersion": "schema-migration-report/v1",
                "status": "compatible",
                "fromVersion": version,
                "toVersion": version,
                "appliedMigrations": [],
                "failureClass": None,
            }
        return {
            "schemaVersion": "schema-migration-report/v1",
            "status": "failed",
            "fromVersion": version,
            "toVersion": None,
            "appliedMigrations": [],
            "failureClass": "CONFIG_ERROR",
        }
