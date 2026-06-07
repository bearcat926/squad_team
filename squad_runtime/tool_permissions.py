from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


class ToolPermissionError(PermissionError):
    def __init__(self, message: str, failure_class: str):
        super().__init__(message)
        self.failure_class = failure_class


@dataclass(frozen=True)
class ToolConfig:
    name: str
    deterministic_replay: bool
    replay_mode: Literal["deterministic", "conditional", "none"]
    dependency_locking: Literal["none", "required"]
    internal_only: bool = False

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "deterministicReplay": self.deterministic_replay,
            "replayMode": self.replay_mode,
            "dependencyLocking": self.dependency_locking,
        }


TOOL_CONFIGS: dict[str, ToolConfig] = {
    "read_file": ToolConfig("read_file", True, "deterministic", "none"),
    "list_files": ToolConfig("list_files", True, "deterministic", "none"),
    "write_file": ToolConfig("write_file", False, "conditional", "required"),
    "apply_patch": ToolConfig("apply_patch", False, "conditional", "required"),
    "run_test": ToolConfig("run_test", False, "conditional", "required"),
    "run_build": ToolConfig("run_build", False, "conditional", "required"),
    "run_lint": ToolConfig("run_lint", False, "conditional", "required"),
    "run_scan": ToolConfig("run_scan", False, "conditional", "required"),
    "register_artifact": ToolConfig("register_artifact", True, "deterministic", "none"),
    "register_verification": ToolConfig("register_verification", True, "deterministic", "none"),
    "request_snapshot_seal": ToolConfig("request_snapshot_seal", True, "deterministic", "none"),
    "seal_snapshot": ToolConfig("seal_snapshot", False, "conditional", "required", internal_only=True),
}

FORBIDDEN_TOOLS = {"run_command", "shell", "exec", "python_eval"}
