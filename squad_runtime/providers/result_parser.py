"""Result parsing for provider dispatch outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ResultParser:
    """Parses provider subprocess output into AgentResult-compatible dicts."""

    def read_result_payload(self, final_result_path: Path, stdout: str) -> dict[str, Any] | None:
        """Read and parse the result payload.

        Priority: final-result.json > stdout JSON.
        Returns None if no valid payload can be extracted.
        """
        raw = final_result_path.read_text(encoding="utf-8-sig") if final_result_path.exists() else stdout
        stripped = raw.strip()
        if not stripped:
            return None
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = self._extract_single_json_object(stripped)
        payload = self._unwrap_cli_result(payload)
        return payload if isinstance(payload, dict) else None

    def _unwrap_cli_result(self, payload: Any) -> Any:
        """Unwrap Claude CLI wrapper format (type=result)."""
        if not isinstance(payload, dict):
            return payload
        if payload.get("type") != "result" or "result" not in payload:
            return payload
        result = payload.get("result")
        if not isinstance(result, str):
            return None
        stripped = result.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return self._extract_single_json_object(stripped)

    def _extract_single_json_object(self, text: str) -> dict[str, Any] | None:
        """Extract the first complete JSON object from text."""
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None
