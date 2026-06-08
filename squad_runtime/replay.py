from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .canonicalization import GENESIS_HASH, compute_event_hash


class ReplayEngine:
    """Reconstructs read-only runtime state from exported FULL_DATA_LOG payloads."""

    def reconstruct_state(self, full_data_log_path: Path) -> dict[str, Any]:
        payload = json.loads(Path(full_data_log_path).read_text(encoding="utf-8"))

        # Verify hash chain before state reconstruction
        chain_result = self.verify_event_chain(payload.get("events", []))
        if not chain_result["valid"] and chain_result["eventCount"] > 0:
            # Check if this is a v1 archive (no hash fields at all) vs a corrupted chain
            has_any_hash = any(e.get("eventPayloadHash") or e.get("eventHash") for e in payload.get("events", []))
            if has_any_hash:
                return {
                    "schemaVersion": "reconstructed-state/v1",
                    "status": "CHAIN_VERIFICATION_FAILED",
                    "chainVerification": chain_result,
                }

        return {
            "schemaVersion": "reconstructed-state/v1",
            "run": payload["run"],
            "nodes": {node["id"]: node["status"] for node in payload.get("nodes", [])},
            "gates": {gate["gateName"]: gate["status"] for gate in payload.get("gates", [])},
            "agentResults": {result["agentId"]: result["status"] for result in payload.get("agentResults", [])},
            "eventCount": len(payload.get("events", [])),
            "finalEventHash": chain_result.get("finalEventHash") or self._final_event_hash(payload.get("events", [])),
            "chainVerification": chain_result,
        }

    def verify_event_chain(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Verify event hash chain integrity.

        Returns:
            {
                "valid": bool,
                "eventCount": int,
                "finalEventHash": str | None,
                "errors": list[str]
            }
        """
        errors: list[str] = []
        prev_hash = GENESIS_HASH
        final_hash: str | None = None

        for event in events:
            seq = event.get("sequenceNumber", event.get("sequence_number", "?"))
            stored_prev = event.get("previousEventHash", event.get("previous_event_hash"))
            stored_payload_hash = event.get("eventPayloadHash", event.get("event_payload_hash"))
            stored_event_hash = event.get("eventHash", event.get("event_hash"))

            # Legacy rows without hash fields
            if stored_payload_hash is None or stored_event_hash is None:
                errors.append(f"sequence {seq}: missing hash fields (legacy row)")
                continue

            if stored_prev != prev_hash:
                errors.append(f"sequence {seq}: previousEventHash mismatch " f"(expected {prev_hash}, got {stored_prev})")

            payload = event.get("payload", {})
            exp_payload_hash, exp_event_hash = compute_event_hash(prev_hash, payload)
            if exp_payload_hash != stored_payload_hash:
                errors.append(f"sequence {seq}: eventPayloadHash mismatch " f"(expected {exp_payload_hash}, got {stored_payload_hash})")
            if exp_event_hash != stored_event_hash:
                errors.append(f"sequence {seq}: eventHash mismatch " f"(expected {exp_event_hash}, got {stored_event_hash})")

            prev_hash = str(stored_event_hash)
            final_hash = stored_event_hash

        return {
            "valid": len(errors) == 0,
            "eventCount": len(events),
            "finalEventHash": final_hash,
            "errors": errors,
        }

    @staticmethod
    def _final_event_hash(events: list[dict[str, Any]]) -> str | None:
        for event in reversed(events):
            if event.get("type") == "event_hash_chain_sealed":
                return event.get("payload", {}).get("finalEventHash")
        return None
