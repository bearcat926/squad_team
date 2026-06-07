from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ReplayEngine:
    """Reconstructs read-only runtime state from exported FULL_DATA_LOG payloads."""

    def reconstruct_state(self, full_data_log_path: Path) -> dict[str, Any]:
        payload = json.loads(Path(full_data_log_path).read_text(encoding="utf-8"))
        return {
            "schemaVersion": "reconstructed-state/v1",
            "run": payload["run"],
            "nodes": {node["id"]: node["status"] for node in payload.get("nodes", [])},
            "gates": {gate["gateName"]: gate["status"] for gate in payload.get("gates", [])},
            "agentResults": {result["agentId"]: result["status"] for result in payload.get("agentResults", [])},
            "eventCount": len(payload.get("events", [])),
            "finalEventHash": self._final_event_hash(payload.get("events", [])),
        }

    @staticmethod
    def _final_event_hash(events: list[dict[str, Any]]) -> str | None:
        for event in reversed(events):
            if event.get("type") == "event_hash_chain_sealed":
                return event.get("payload", {}).get("finalEventHash")
        return None
