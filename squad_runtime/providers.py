from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .agent_contracts import AgentResult, validate_agent_result
from .agent_registry import AgentProfile
from .context import AgentContextBuilder
from .runtime import Runtime
from .state import NodeStatus


@dataclass(frozen=True)
class ProviderHealth:
    provider: str
    available: bool
    detail: str
    provider_type: str = "unknown"
    identity_verified: bool = False


class FakeCliProvider:
    name = "fake_cli"

    def health(self) -> ProviderHealth:
        return ProviderHealth(self.name, True, "deterministic provider available", "deterministic", True)

    def execute(
        self,
        runtime: Runtime,
        node,
        profile: AgentProfile,
        synthetic: bool = False,
        provider_fallback_triggered: bool = False,
        fallback_reason: str | None = None,
    ) -> AgentResult:
        dispatch_id = f"dispatch-{uuid.uuid4().hex[:12]}"
        runtime.events.append(
            node.run_id,
            "llm_session_started",
            {"dispatchId": dispatch_id, "agentId": profile.agent_id, "provider": self.name, "synthetic": synthetic, "providerFallbackTriggered": provider_fallback_triggered},
            critical=True,
        )
        current = runtime.get_node(node.id)
        if current.status == NodeStatus.READY:
            runtime.transition_node(current.id, NodeStatus.READY, NodeStatus.RUNNING, "fake cli dispatch")
        result = AgentResult(
            taskNodeId=node.id,
            agentId=profile.agent_id,
            status="pass",
            summary=f"Fake CLI result for {profile.agent_id}",
            evidence=[{"type": "synthetic" if synthetic else "fake_cli", "content": "deterministic evidence"}],
            artifacts=[],
            risks=[],
            nextActions=[],
            confidence=1.0,
            workedAgainstCheckpoint=node.checkpoint_id,
            agentContractVersion="v1",
        )
        runtime.persist_agent_result(
            result,
            provider_used=self.name,
            provider_type="deterministic",
            provider_identity_verified=True,
            provider_fallback_triggered=provider_fallback_triggered,
            fallback_reason=fallback_reason,
            synthetic=synthetic,
        )
        outcome = runtime.apply_agent_result(result)
        runtime.events.append(
            node.run_id,
            "llm_session_completed",
            {"dispatchId": dispatch_id, "agentId": profile.agent_id, "provider": self.name, "outcome": outcome},
            critical=True,
        )
        return result


class LocalCliProvider:
    def __init__(
        self,
        name: str,
        executable: str,
        command_args: list[str] | None = None,
        provider_type: str = "real_llm",
        identity_verified: bool = False,
        timeout_sec: float | None = None,
    ):
        self.name = name
        self.executable = executable
        self.command_args = command_args
        self.provider_type = provider_type
        self.identity_verified = identity_verified
        self.timeout_sec = timeout_sec if timeout_sec is not None else float(os.environ.get("SQUAD_PROVIDER_TIMEOUT_SEC", "600"))
        self.extra_env: dict[str, str] = {}

    def health(self) -> ProviderHealth:
        source = shutil.which(self.executable)
        if not source:
            return ProviderHealth(self.name, False, "executable not found", self.provider_type, False)
        try:
            completed = subprocess.run([source, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        except Exception as exc:  # pragma: no cover - host dependent
            return ProviderHealth(self.name, False, str(exc), self.provider_type, False)
        if completed.returncode != 0:
            return ProviderHealth(self.name, False, (completed.stderr or completed.stdout).strip(), self.provider_type, False)
        return ProviderHealth(self.name, True, completed.stdout.strip() or source, self.provider_type, True)

    def execute(
        self,
        runtime: Runtime,
        node,
        profile: AgentProfile,
        synthetic: bool = False,
        provider_fallback_triggered: bool = False,
        fallback_reason: str | None = None,
    ) -> AgentResult | None:
        dispatch_id = f"dispatch-{uuid.uuid4().hex[:12]}"
        dispatch_dir = runtime.squad_dir / "runs" / node.run_id / "dispatches" / dispatch_id
        dispatch_dir.mkdir(parents=True, exist_ok=True)
        final_result_path = dispatch_dir / "final-result.json"
        stdout_path = dispatch_dir / "stdout.log"
        stderr_path = dispatch_dir / "stderr.log"
        context = AgentContextBuilder(runtime, _SingleAgentRegistry(profile)).build(node.id)
        (dispatch_dir / "context.json").write_text(json.dumps(asdict(context), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        prompt = self._build_prompt(context)
        (dispatch_dir / "prompt.md").write_text(prompt, encoding="utf-8")
        (dispatch_dir / "agent-result.schema.json").write_text(json.dumps(_agent_result_schema(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        runtime.events.append(
            node.run_id,
            "llm_session_started",
            {"dispatchId": dispatch_id, "agentId": profile.agent_id, "provider": self.name, "synthetic": synthetic, "providerFallbackTriggered": provider_fallback_triggered},
            critical=True,
        )
        current = runtime.get_node(node.id)
        if current.status == NodeStatus.READY:
            runtime.transition_node(current.id, NodeStatus.READY, NodeStatus.RUNNING, "local cli dispatch")
        health = self.health()
        if not health.available:
            (dispatch_dir / "provider-health.json").write_text(json.dumps(asdict(health), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            self._mark_unavailable(runtime, node, "provider unavailable")
            runtime.events.append(
                node.run_id,
                "provider_blocked",
                {
                    "nodeId": node.id,
                    "agentId": profile.agent_id,
                    "dispatchId": dispatch_id,
                    "provider": self.name,
                    "detail": health.detail,
                },
                critical=True,
            )
            return None
        provider_identity_verified = self.identity_verified or health.identity_verified
        command = self._command()
        env = os.environ.copy()
        env.update(self.extra_env)
        env.update(
            {
                "SQUAD_DISPATCH_DIR": str(dispatch_dir),
                "SQUAD_FINAL_RESULT_PATH": str(final_result_path),
                "SQUAD_CONTEXT_PATH": str(dispatch_dir / "context.json"),
                "SQUAD_PROMPT_PATH": str(dispatch_dir / "prompt.md"),
            }
        )
        try:
            completed = subprocess.run(command, cwd=dispatch_dir, env=env, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=self.timeout_sec)
        except subprocess.TimeoutExpired as exc:
            stdout_path.write_text(exc.stdout or "", encoding="utf-8")
            stderr_path.write_text(exc.stderr or "", encoding="utf-8")
            (dispatch_dir / "timeout.json").write_text(json.dumps({"timeoutSec": self.timeout_sec}, ensure_ascii=False, indent=2), encoding="utf-8")
            self._mark_unavailable(runtime, node, "timeout")
            runtime.events.append(node.run_id, "agent_timeout", {"nodeId": node.id, "agentId": profile.agent_id, "dispatchId": dispatch_id, "provider": self.name}, critical=True)
            return None
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        if completed.returncode != 0:
            self._block_node(runtime, node, "invalid_agent_result", {"exitCode": completed.returncode})
            runtime.events.append(node.run_id, "invalid_agent_result", {"nodeId": node.id, "agentId": profile.agent_id, "dispatchId": dispatch_id, "exitCode": completed.returncode}, critical=True)
            return None
        payload = self._read_result_payload(final_result_path, completed.stdout or "")
        if payload is None:
            self._block_node(runtime, node, "invalid_agent_result", {"reason": "invalid_output"})
            runtime.events.append(node.run_id, "invalid_agent_result", {"nodeId": node.id, "agentId": profile.agent_id, "dispatchId": dispatch_id, "reason": "invalid_output"}, critical=True)
            return None
        try:
            result = AgentResult(**payload)
        except TypeError as exc:
            self._block_node(runtime, node, "invalid_agent_result", {"reason": str(exc)})
            runtime.events.append(node.run_id, "invalid_agent_result", {"nodeId": node.id, "agentId": profile.agent_id, "dispatchId": dispatch_id, "reason": str(exc)}, critical=True)
            return None
        if result.taskNodeId != node.id or result.agentId != profile.agent_id:
            self._block_node(runtime, node, "invalid_agent_result", {"reason": "metadata_mismatch"})
            runtime.events.append(node.run_id, "invalid_agent_result", {"nodeId": node.id, "agentId": profile.agent_id, "dispatchId": dispatch_id, "reason": "metadata_mismatch"}, critical=True)
            return None
        if result.workedAgainstCheckpoint != node.checkpoint_id:
            self._block_node(runtime, node, "checkpoint_mismatch", {"expected": node.checkpoint_id, "actual": result.workedAgainstCheckpoint})
            runtime.events.append(node.run_id, "checkpoint_mismatch", {"nodeId": node.id, "agentId": profile.agent_id, "dispatchId": dispatch_id, "expected": node.checkpoint_id, "actual": result.workedAgainstCheckpoint}, critical=True)
            return None
        validation = validate_agent_result(result, runtime.squad_dir / "artifacts", node.checkpoint_id)
        if not validation.valid:
            self._block_node(runtime, node, "invalid_agent_result", {"errors": validation.errors})
            runtime.events.append(node.run_id, "invalid_agent_result", {"nodeId": node.id, "agentId": profile.agent_id, "dispatchId": dispatch_id, "errors": validation.errors}, critical=True)
            return None
        runtime.persist_agent_result(
            result,
            provider_used=self.name,
            provider_type=self.provider_type,
            provider_identity_verified=provider_identity_verified,
            provider_fallback_triggered=provider_fallback_triggered,
            fallback_reason=fallback_reason,
            synthetic=synthetic,
        )
        outcome = runtime.apply_agent_result(result)
        runtime.events.append(node.run_id, "llm_session_completed", {"dispatchId": dispatch_id, "agentId": profile.agent_id, "provider": self.name, "outcome": outcome}, critical=True)
        return result

    def _command(self, prompt: str | None = None) -> list[str]:
        source = shutil.which(self.executable) or self.executable
        if self.command_args is not None:
            return [source, *self.command_args]
        return [
            source,
            "-p",
            "--bare",
            "--disable-slash-commands",
            "--system-prompt",
            "You are a JSON-only API. You have no tools. Never emit tool_call, function, markdown, commentary, or XML tags. Return only the requested JSON object.",
            "--output-format",
            "json",
            "--no-session-persistence",
        ]

    def _read_result_payload(self, final_result_path: Path, stdout: str) -> dict[str, Any] | None:
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
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    def _build_prompt(self, context) -> str:
        return (
            "You are the configured Squad Runtime agent. Return exactly one top-level JSON object matching AgentResult.\n"
            "Do not include Markdown fences, commentary, or multiple JSON objects.\n"
            "Do not inspect files, claim to read files, or emit tool calls; use only the context in this prompt.\n"
            "Do not ask for more context. The task, identifiers, checkpoint, and required JSON shape are provided below.\n"
            "For this provider dispatch, the required runtime output is AgentResult even if the agent profile has a different planning contract.\n"
            "Do not mention or use LeadDecisionChangeSet in this dispatch result; return AgentResult only.\n"
            "Return immediately after the JSON object.\n"
            f"Agent: {context.agent_id}\n"
            f"Role: {context.role}\n"
            f"Task Node ID: {context.task_node_id}\n"
            f"Task: {context.task_goal}\n"
            f"Checkpoint: {context.checkpoint_id}\n"
            "Runtime Output Contract: AgentResult\n"
            f"Forbidden paths: {', '.join(context.forbidden_paths)}\n"
            "Runtime facts available to this dispatch:\n"
            f"{json.dumps(context.runtime_facts, ensure_ascii=False, sort_keys=True)}\n"
            "Prior dependency summaries available to this dispatch:\n"
            f"{json.dumps(context.dependency_summaries, ensure_ascii=False, sort_keys=True)}\n"
            "Use the runtime facts and dependency summaries as the authoritative evidence source for this dispatch.\n"
            "If the provided facts are sufficient for your role-specific acceptance decision, return status pass.\n"
            "Required JSON shape:\n"
            "{\n"
            f'  "taskNodeId": "{context.task_node_id}",\n'
            f'  "agentId": "{context.agent_id}",\n'
            '  "status": "pass|fail|blocked",\n'
            '  "summary": "concise result",\n'
            '  "evidence": [{"type": "agent", "content": "evidence"}],\n'
            '  "artifacts": [],\n'
            '  "risks": [{"level": "low", "description": "risk description"}],\n'
            '  "nextActions": [{"action": "next action", "reason": "why"}],\n'
            '  "confidence": 0.0,\n'
            f'  "workedAgainstCheckpoint": "{context.checkpoint_id}",\n'
            '  "agentContractVersion": "v1"\n'
            "}\n"
        )

    def _block_node(self, runtime: Runtime, node, reason_code: str, metadata: dict[str, Any]) -> None:
        current = runtime.get_node(node.id)
        if current.status == NodeStatus.RUNNING:
            runtime.transition_node(node.id, NodeStatus.RUNNING, NodeStatus.BLOCKED, reason_code, blocked_reason_code=reason_code, metadata=metadata)

    def _mark_unavailable(self, runtime: Runtime, node, reason: str) -> None:
        current = runtime.get_node(node.id)
        if current.status == NodeStatus.RUNNING:
            runtime.transition_node(node.id, NodeStatus.RUNNING, NodeStatus.AGENT_UNAVAILABLE, reason)


class ProviderRegistry:
    def __init__(self, providers: dict[str, Any] | None = None):
        self.providers = providers or {
            "fake_cli": FakeCliProvider(),
            "claude_cli": LocalCliProvider("claude_cli", "claude"),
            "codex_cli": LocalCliProvider("codex_cli", "codex"),
        }

    @classmethod
    def default(cls) -> "ProviderRegistry":
        return cls()

    def doctor(self) -> list[ProviderHealth]:
        return [provider.health() for provider in self.providers.values()]

    def get(self, provider_name: str):
        return self.providers[provider_name]


class _SingleAgentRegistry:
    def __init__(self, profile: AgentProfile):
        self.profile = profile

    def get(self, agent_id: str) -> AgentProfile:
        return self.profile


def _agent_result_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "taskNodeId",
            "agentId",
            "status",
            "summary",
            "evidence",
            "artifacts",
            "risks",
            "nextActions",
            "confidence",
            "workedAgainstCheckpoint",
            "agentContractVersion",
        ],
        "properties": {
            "status": {"enum": ["pass", "fail", "blocked"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    }
