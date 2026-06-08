from __future__ import annotations

import fnmatch
import hashlib
import json
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agent_registry import AgentRegistry
from .runtime import Runtime
from .security.paths import UnsafePathError, validate_path_within_root
from .snapshot import SnapshotManager
from .tool_permissions import FORBIDDEN_TOOLS, TOOL_CONFIGS, ToolPermissionError


@dataclass(frozen=True)
class ToolResult:
    content: str | None = None
    path: str | None = None
    exit_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    base_snapshot_id: str | None = None
    result_snapshot_id: str | None = None


@dataclass
class ToolSessionConfig:
    max_tool_rounds: int = 5
    tool_call_timeout_seconds: int = 30
    session_timeout_seconds: int = 180


@dataclass
class ToolSession:
    session_id: str
    node_id: str
    agent_id: str
    run_id: str
    started_at: float
    config: ToolSessionConfig
    round_count: int = 0
    status: str = "active"
    calls: list = field(default_factory=list)


class ControlledToolAdapter:
    """Role-scoped tool adapter for LLM agent dispatches."""

    def __init__(
        self,
        runtime: Runtime,
        workspace_root: Path,
        registry: AgentRegistry,
        test_commands: dict[str, list[str]] | None = None,
        build_commands: dict[str, list[str]] | None = None,
        lint_commands: dict[str, list[str]] | None = None,
        scan_commands: dict[str, list[str]] | None = None,
    ):
        self.runtime = runtime
        self.workspace_root = Path(workspace_root).resolve()
        self.registry = registry
        self.test_commands = test_commands or {}
        self.build_commands = build_commands or {}
        self.lint_commands = lint_commands or {}
        self.scan_commands = scan_commands or {}

    def call_tool(self, node_id: str, tool_name: str, args: dict[str, Any]) -> ToolResult:
        if tool_name in FORBIDDEN_TOOLS:
            self._deny(node_id, tool_name, str(args.get("path", "")), "Forbidden tool", "SECURITY_VIOLATION")
        if tool_name == "seal_snapshot":
            self._deny(node_id, tool_name, "", "seal_snapshot is internal only", "POLICY_VIOLATION")
        if tool_name not in TOOL_CONFIGS:
            self._deny(node_id, tool_name, str(args.get("path", "")), "Unknown tool", "CONFIG_ERROR")
        return getattr(self, tool_name)(node_id, **args)

    def read_file(self, node_id: str, path: str) -> ToolResult:
        node, rel = self._authorize_path(node_id, "read_file", path, "read")
        content = (self.workspace_root / rel).read_text(encoding="utf-8")
        self._record_tool_event(node.run_id, node_id, node.owner_agent_id, "read_file", {"path": rel})
        return ToolResult(content=content, path=rel)

    def list_files(self, node_id: str, glob: str = "**/*") -> ToolResult:
        node = self.runtime.get_node(node_id)
        self._require_tool(node_id, "list_files", "read")
        files = []
        for path in sorted(self.workspace_root.glob(glob)):
            if path.is_file() and not self._is_forbidden_relative(path.relative_to(self.workspace_root).as_posix()):
                files.append(path.relative_to(self.workspace_root).as_posix())
        self._record_tool_event(node.run_id, node_id, node.owner_agent_id, "list_files", {"glob": glob, "count": len(files)})
        return ToolResult(content=json.dumps(files, ensure_ascii=False), path=None)

    def write_file(self, node_id: str, path: str, content: str, base_snapshot_id: str) -> ToolResult:
        node, rel = self._authorize_path(node_id, "write_file", path, "write")
        self._require_matching_base_snapshot(node_id, base_snapshot_id)
        target = self.workspace_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        snapshot = SnapshotManager(self.workspace_root, self.runtime.squad_dir).seal_snapshot()
        self._record_tool_event(
            node.run_id,
            node_id,
            node.owner_agent_id,
            "write_file",
            {"path": rel, "baseSnapshotId": base_snapshot_id, "resultSnapshotId": snapshot.snapshot_id},
        )
        return ToolResult(path=rel, base_snapshot_id=base_snapshot_id, result_snapshot_id=snapshot.snapshot_id)

    def apply_patch(self, node_id: str, path: str, old: str, new: str, base_snapshot_id: str) -> ToolResult:
        node, rel = self._authorize_path(node_id, "apply_patch", path, "write")
        self._require_matching_base_snapshot(node_id, base_snapshot_id)
        target = self.workspace_root / rel
        content = target.read_text(encoding="utf-8")
        if old not in content:
            self._deny(node_id, "apply_patch", rel, "Patch search text not found", "CONFIG_ERROR")
        target.write_text(content.replace(old, new, 1), encoding="utf-8")
        snapshot = SnapshotManager(self.workspace_root, self.runtime.squad_dir).seal_snapshot()
        self._record_tool_event(
            node.run_id,
            node_id,
            node.owner_agent_id,
            "apply_patch",
            {"path": rel, "baseSnapshotId": base_snapshot_id, "resultSnapshotId": snapshot.snapshot_id},
        )
        return ToolResult(path=rel, base_snapshot_id=base_snapshot_id, result_snapshot_id=snapshot.snapshot_id)

    def run_test(self, node_id: str, test_id: str) -> ToolResult:
        return self._run_registered_command(node_id, "run_test", test_id, self.test_commands)

    def run_build(self, node_id: str, build_id: str) -> ToolResult:
        return self._run_registered_command(node_id, "run_build", build_id, self.build_commands)

    def run_lint(self, node_id: str, lint_id: str) -> ToolResult:
        return self._run_registered_command(node_id, "run_lint", lint_id, self.lint_commands)

    def run_scan(self, node_id: str, scan_id: str) -> ToolResult:
        return self._run_registered_command(node_id, "run_scan", scan_id, self.scan_commands)

    def register_artifact(self, node_id: str, path: str, type: str, purpose: str, metadata: dict[str, Any] | None = None) -> ToolResult:
        node, rel = self._authorize_path(node_id, "register_artifact", path, "read")
        self._record_tool_event(
            node.run_id,
            node_id,
            node.owner_agent_id,
            "register_artifact",
            {"path": rel, "type": type, "purpose": purpose, "metadata": metadata or {}},
        )
        self.runtime.record_event(
            node.run_id,
            "artifact_produced",
            {"name": Path(rel).name, "path": rel, "type": type, "purpose": purpose, "metadata": metadata or {}},
        )
        return ToolResult(path=rel)

    def register_verification(self, node_id: str, kind: str, result: str, metadata: dict[str, Any] | None = None) -> ToolResult:
        node = self.runtime.get_node(node_id)
        self._require_tool(node_id, "register_verification", "test")
        metadata = metadata or {}
        payload = {"kind": kind, "status": result, **metadata, "metadata": metadata}
        self._record_tool_event(node.run_id, node_id, node.owner_agent_id, "register_verification", payload)
        self.runtime.record_event(node.run_id, "verification_result", payload)
        return ToolResult(content=json.dumps(payload, ensure_ascii=False))

    def request_snapshot_seal(self, node_id: str, reason: str) -> ToolResult:
        node = self.runtime.get_node(node_id)
        self._require_tool(node_id, "request_snapshot_seal", "read")
        self._record_tool_event(node.run_id, node_id, node.owner_agent_id, "request_snapshot_seal", {"reason": reason})
        return ToolResult(content="snapshot seal requested")

    def _run_registered_command(self, node_id: str, tool_name: str, command_id: str, registry: dict[str, list[str]]) -> ToolResult:
        node = self.runtime.get_node(node_id)
        self._require_tool(node_id, tool_name, "test")
        command = registry.get(command_id)
        if command is None:
            self._deny(node_id, tool_name, command_id, f"Unknown command id {command_id}", "CONFIG_ERROR")
        assert command is not None
        completed = subprocess.run(command, cwd=self.workspace_root, capture_output=True, text=True, timeout=120, check=False)
        self._record_tool_event(
            node.run_id,
            node_id,
            node.owner_agent_id,
            tool_name,
            {"commandId": command_id, "exitCode": completed.returncode},
        )
        return ToolResult(exit_code=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)

    def _authorize_path(self, node_id: str, tool_name: str, path: str, capability: str) -> tuple[Any, str]:
        node = self.runtime.get_node(node_id)
        self._require_tool(node_id, tool_name, capability)
        try:
            resolved = validate_path_within_root(path, self.workspace_root)
        except UnsafePathError:
            self._deny(node_id, tool_name, path, "Path escapes workspace", "SECURITY_VIOLATION")
        rel = resolved.relative_to(self.workspace_root).as_posix()
        if self._is_forbidden_relative(rel):
            self._deny(node_id, tool_name, rel, "Forbidden path", "SECURITY_VIOLATION")
        profile = self.registry.get(node.owner_agent_id)
        patterns = profile.allowed_read_paths if capability == "read" else profile.allowed_write_paths
        if patterns and not self._matches_any(rel, patterns):
            self._deny(node_id, tool_name, rel, f"{capability} path not allowed for role", "POLICY_VIOLATION")
        return node, rel

    def _require_tool(self, node_id: str, tool_name: str, capability: str) -> None:
        node = self.runtime.get_node(node_id)
        profile = self.registry.get(node.owner_agent_id)
        config = TOOL_CONFIGS[tool_name]
        if config.internal_only:
            self._deny(node_id, tool_name, "", "Internal tool", "POLICY_VIOLATION")
        if capability not in profile.allowed_tools and tool_name not in profile.allowed_tools:
            self._deny(node_id, tool_name, "", f"Tool {tool_name} not allowed for {profile.agent_id}", "POLICY_VIOLATION")

    def _require_matching_base_snapshot(self, node_id: str, base_snapshot_id: str) -> None:
        node = self.runtime.get_node(node_id)
        if base_snapshot_id != node.checkpoint_id:
            self._deny(node_id, "snapshot_guard", "", "baseSnapshotId does not match node checkpoint", "CHECKPOINT_MISMATCH")

    def _deny(self, node_id: str, tool_name: str, path: str, reason: str, failure_class: str) -> None:
        node = self.runtime.get_node(node_id)
        self.runtime.record_event(
            node.run_id,
            "tool_permission_denied",
            {
                "nodeId": node.id,
                "agentId": node.owner_agent_id,
                "toolName": tool_name,
                "path": path,
                "reason": reason,
                "failureClass": failure_class,
            },
        )
        raise ToolPermissionError(reason, failure_class)

    def _record_tool_event(self, run_id: str, node_id: str, agent_id: str, tool_name: str, payload: dict[str, Any]) -> None:
        config_payload = TOOL_CONFIGS[tool_name].to_event_payload()
        event_payload = {
            "schemaVersion": "tool-call/v1",
            "nodeId": node_id,
            "agentId": agent_id,
            "toolName": tool_name,
            **config_payload,
            **payload,
        }
        event_payload["eventHash"] = (
            "sha256:" + hashlib.sha256(json.dumps(event_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        )
        self.runtime.record_event(run_id, "tool_call", event_payload)

    @staticmethod
    def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
        for pattern in patterns:
            if pattern == "**/*":
                return True
            if pattern.startswith("**/*.") and path.endswith(pattern.removeprefix("**/*")):
                return True
            if Path(path).match(pattern) or fnmatch.fnmatch(path, pattern):
                return True
        return False

    @staticmethod
    def _is_forbidden_relative(path: str) -> bool:
        forbidden = (".squad/*", ".squad/**", "**/.squad/*", "**/.squad/**", ".squad/token", ".squad/squad.db", ".squad/events.ndjson")
        return any(Path(path).match(pattern) or fnmatch.fnmatch(path, pattern) for pattern in forbidden)

    # ------------------------------------------------------------------
    # Tool Session lifecycle
    # ------------------------------------------------------------------

    def start_tool_session(self, node_id: str, config: ToolSessionConfig | None = None) -> ToolSession:
        """Start a new tool session for a node dispatch."""
        node = self.runtime.get_node(node_id)
        config = config or ToolSessionConfig()
        session = ToolSession(
            session_id=f"tool-session-{uuid.uuid4().hex[:12]}",
            node_id=node_id,
            agent_id=node.owner_agent_id,
            run_id=node.run_id,
            started_at=time.time(),
            config=config,
        )
        self.runtime.record_event(
            node.run_id,
            "tool_session_started",
            {
                "sessionId": session.session_id,
                "nodeId": node_id,
                "agentId": node.owner_agent_id,
                "maxToolRounds": config.max_tool_rounds,
                "toolCallTimeoutSeconds": config.tool_call_timeout_seconds,
                "sessionTimeoutSeconds": config.session_timeout_seconds,
            },
        )
        return session

    def call_tool_in_session(self, session: ToolSession, tool_name: str, args: dict[str, Any]) -> ToolResult:
        """Execute a tool call within a session, enforcing round limits and timeouts."""
        # Check session timeout
        elapsed = time.time() - session.started_at
        if elapsed > session.config.session_timeout_seconds:
            self._complete_tool_session(session, "timeout", reason="session_timeout", detail=f"Session exceeded {session.config.session_timeout_seconds}s")
            raise ToolPermissionError("Tool session timed out", "TOOL_LOOP_TIMEOUT")

        # Check round limit
        if session.round_count >= session.config.max_tool_rounds:
            self._complete_tool_session(session, "max_rounds_exceeded", detail=f"Exceeded {session.config.max_tool_rounds} rounds")
            raise ToolPermissionError("Tool loop max rounds exceeded", "TOOL_LOOP_MAX_ROUNDS")

        # Emit tool_call_requested
        self.runtime.record_event(
            session.run_id,
            "tool_call_requested",
            {
                "sessionId": session.session_id,
                "nodeId": session.node_id,
                "agentId": session.agent_id,
                "toolName": tool_name,
                "round": session.round_count + 1,
                "args": {k: v for k, v in args.items() if k != "content"},  # Redact content for audit
            },
            critical=True,
        )

        # Validate tool is allowed
        if tool_name in FORBIDDEN_TOOLS:
            self.runtime.record_event(
                session.run_id,
                "tool_call_denied",
                {
                    "sessionId": session.session_id,
                    "nodeId": session.node_id,
                    "agentId": session.agent_id,
                    "toolName": tool_name,
                    "reason": "illegal_tool",
                    "denialCode": "illegal_tool",
                },
                critical=True,
            )
            self._complete_tool_session(session, "denied", reason="illegal_tool")
            raise ToolPermissionError(f"Illegal tool: {tool_name}", "ILLEGAL_TOOL")

        if tool_name not in TOOL_CONFIGS:
            self.runtime.record_event(
                session.run_id,
                "tool_call_denied",
                {
                    "sessionId": session.session_id,
                    "nodeId": session.node_id,
                    "agentId": session.agent_id,
                    "toolName": tool_name,
                    "reason": "unknown_tool",
                    "denialCode": "illegal_tool",
                },
                critical=True,
            )
            self._complete_tool_session(session, "denied", reason="unknown_tool")
            raise ToolPermissionError(f"Unknown tool: {tool_name}", "CONFIG_ERROR")

        # Emit tool_call_allowed
        self.runtime.record_event(
            session.run_id,
            "tool_call_allowed",
            {
                "sessionId": session.session_id,
                "nodeId": session.node_id,
                "agentId": session.agent_id,
                "toolName": tool_name,
                "round": session.round_count + 1,
            },
            critical=True,
        )

        # Execute the tool call
        try:
            result = self.call_tool(session.node_id, tool_name, args)
            session.round_count += 1

            # Emit tool_call_completed
            self.runtime.record_event(
                session.run_id,
                "tool_call_completed",
                {
                    "sessionId": session.session_id,
                    "nodeId": session.node_id,
                    "agentId": session.agent_id,
                    "toolName": tool_name,
                    "round": session.round_count,
                    "status": "success",
                },
                critical=True,
            )
            session.calls.append({"toolName": tool_name, "status": "success", "round": session.round_count})
            return result
        except ToolPermissionError:
            # Permission denied already recorded by call_tool
            session.round_count += 1
            self.runtime.record_event(
                session.run_id,
                "tool_call_completed",
                {
                    "sessionId": session.session_id,
                    "nodeId": session.node_id,
                    "agentId": session.agent_id,
                    "toolName": tool_name,
                    "round": session.round_count,
                    "status": "denied",
                },
                critical=True,
            )
            session.calls.append({"toolName": tool_name, "status": "denied", "round": session.round_count})
            raise
        except Exception as exc:
            session.round_count += 1
            self.runtime.record_event(
                session.run_id,
                "tool_call_completed",
                {
                    "sessionId": session.session_id,
                    "nodeId": session.node_id,
                    "agentId": session.agent_id,
                    "toolName": tool_name,
                    "round": session.round_count,
                    "status": "error",
                    "error": str(exc),
                },
                critical=True,
            )
            session.calls.append({"toolName": tool_name, "status": "error", "round": session.round_count})
            raise

    def complete_tool_session(self, session: ToolSession, outcome: str = "success") -> None:
        """Explicitly complete a tool session."""
        self._complete_tool_session(session, outcome)

    def _complete_tool_session(self, session: ToolSession, status: str, reason: str | None = None, detail: str | None = None) -> None:
        """Internal: emit tool_session_completed event."""
        if session.status != "active":
            return  # Already completed
        session.status = status
        elapsed_ms = int((time.time() - session.started_at) * 1000)
        self.runtime.record_event(
            session.run_id,
            "tool_session_completed",
            {
                "sessionId": session.session_id,
                "nodeId": session.node_id,
                "agentId": session.agent_id,
                "status": status,
                "reason": reason,
                "detail": detail,
                "roundCount": session.round_count,
                "elapsedMs": elapsed_ms,
                "calls": session.calls,
            },
            critical=True,
        )
