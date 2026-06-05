"""Workspace management for provider dispatch directories."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..security.paths import validate_path_within_root


class Workspace:
    """Manages dispatch directory layout and file artifacts.

    All paths are validated to remain within the squad_dir root.
    """

    def __init__(self, squad_dir: Path, run_id: str, dispatch_id: str):
        self.squad_dir = Path(squad_dir)
        self.dispatch_dir = self.squad_dir / "runs" / run_id / "dispatches" / dispatch_id
        self.dispatch_dir.mkdir(parents=True, exist_ok=True)

    @property
    def context_path(self) -> Path:
        return self.dispatch_dir / "context.json"

    @property
    def prompt_path(self) -> Path:
        return self.dispatch_dir / "prompt.md"

    @property
    def schema_path(self) -> Path:
        return self.dispatch_dir / "agent-result.schema.json"

    @property
    def stdout_path(self) -> Path:
        return self.dispatch_dir / "stdout.log"

    @property
    def stderr_path(self) -> Path:
        return self.dispatch_dir / "stderr.log"

    @property
    def final_result_path(self) -> Path:
        return self.dispatch_dir / "final-result.json"

    @property
    def timeout_path(self) -> Path:
        return self.dispatch_dir / "timeout.json"

    @property
    def health_path(self) -> Path:
        return self.dispatch_dir / "provider-health.json"

    def validate_path(self, path: str | Path) -> Path:
        """Validate that a path is within the squad_dir root."""
        return validate_path_within_root(path, self.squad_dir)

    def write_context(self, context: Any) -> None:
        """Write context bundle as JSON."""
        self.context_path.write_text(
            json.dumps(asdict(context), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def write_prompt(self, prompt: str) -> None:
        """Write the prompt markdown."""
        self.prompt_path.write_text(prompt, encoding="utf-8")

    def write_schema(self, schema: dict[str, Any]) -> None:
        """Write the agent result JSON schema."""
        self.schema_path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def write_stdout(self, content: str) -> None:
        """Write captured stdout."""
        self.stdout_path.write_text(content or "", encoding="utf-8")

    def write_stderr(self, content: str) -> None:
        """Write captured stderr."""
        self.stderr_path.write_text(content or "", encoding="utf-8")

    def write_timeout(self, timeout_sec: float) -> None:
        """Write timeout marker."""
        self.timeout_path.write_text(
            json.dumps({"timeoutSec": timeout_sec}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def write_health(self, health: Any) -> None:
        """Write provider health snapshot."""
        self.health_path.write_text(
            json.dumps(asdict(health), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
