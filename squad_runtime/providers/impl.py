"""Provider implementations for Squad Runtime."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from typing import Any

from ..agent_contracts import AgentResult, validate_agent_result
from ..agent_registry import AgentProfile
from ..context import AgentContextBuilder
from ..runtime import Runtime
from ..state import NodeStatus
from .base import ProviderHealth
from .process_runner import ProcessRunner
from .prompt_builder import PromptBuilder
from .rate_limiter import ProviderRateLimiter
from .result_parser import ResultParser
from .workspace import Workspace


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
            {
                "dispatchId": dispatch_id,
                "agentId": profile.agent_id,
                "provider": self.name,
                "synthetic": synthetic,
                "providerFallbackTriggered": provider_fallback_triggered,
            },
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
        rate_limiter: ProviderRateLimiter | None = None,
    ):
        self.name = name
        self.executable = executable
        self.command_args = command_args
        self.provider_type = provider_type
        self.identity_verified = identity_verified
        self.timeout_sec = timeout_sec if timeout_sec is not None else float(os.environ.get("SQUAD_PROVIDER_TIMEOUT_SEC", "600"))
        self.rate_limiter = rate_limiter or ProviderRateLimiter.from_env()
        self.extra_env: dict[str, str] = {}
        self._runner = ProcessRunner(executable, command_args, self.timeout_sec, self.extra_env)
        self._prompt_builder = PromptBuilder()
        self._result_parser = ResultParser()

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
        workspace = Workspace(runtime.squad_dir, node.run_id, dispatch_id)
        context = AgentContextBuilder(runtime, _SingleAgentRegistry(profile)).build(node.id)
        workspace.write_context(context)
        prompt = self._prompt_builder.build(context)
        workspace.write_prompt(prompt)
        workspace.write_schema(_agent_result_schema())
        runtime.events.append(
            node.run_id,
            "llm_session_started",
            {
                "dispatchId": dispatch_id,
                "agentId": profile.agent_id,
                "provider": self.name,
                "synthetic": synthetic,
                "providerFallbackTriggered": provider_fallback_triggered,
            },
            critical=True,
        )
        current = runtime.get_node(node.id)
        if current.status == NodeStatus.READY:
            runtime.transition_node(current.id, NodeStatus.READY, NodeStatus.RUNNING, "local cli dispatch")
        health = self.health()
        if not health.available:
            workspace.write_health(health)
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
        wait = self.rate_limiter.wait_before_dispatch(self.name)
        if wait.waited_seconds > 0:
            runtime.events.append(
                node.run_id,
                "provider_rate_limit_wait",
                {
                    "nodeId": node.id,
                    "agentId": profile.agent_id,
                    "dispatchId": dispatch_id,
                    "provider": self.name,
                    "waitSeconds": wait.waited_seconds,
                    "reason": wait.reason,
                },
                critical=True,
            )
        env_overrides = {
            "SQUAD_DISPATCH_DIR": str(workspace.dispatch_dir),
            "SQUAD_FINAL_RESULT_PATH": str(workspace.final_result_path),
            "SQUAD_CONTEXT_PATH": str(workspace.context_path),
            "SQUAD_PROMPT_PATH": str(workspace.prompt_path),
        }
        self._runner.extra_env = self.extra_env
        completed = self._runner.run(workspace.dispatch_dir, prompt, env_overrides)
        if completed is None:
            workspace.write_stdout("")
            workspace.write_stderr("")
            workspace.write_timeout(self.timeout_sec)
            self._mark_unavailable(runtime, node, "timeout")
            runtime.events.append(
                node.run_id, "agent_timeout", {"nodeId": node.id, "agentId": profile.agent_id, "dispatchId": dispatch_id, "provider": self.name}, critical=True
            )
            return None
        workspace.write_stdout(completed.stdout or "")
        workspace.write_stderr(completed.stderr or "")
        if completed.returncode != 0:
            output = "\n".join([completed.stdout or "", completed.stderr or ""])
            rate_limit = self.rate_limiter.record_provider_error(self.name, output)
            if rate_limit.is_rate_limited:
                self._mark_unavailable(runtime, node, "provider rate limited")
                rate_limit_payload = {
                    "nodeId": node.id,
                    "agentId": profile.agent_id,
                    "dispatchId": dispatch_id,
                    "provider": self.name,
                    "statusCode": rate_limit.status_code,
                    "cooldownSeconds": rate_limit.cooldown_seconds,
                    "reason": rate_limit.reason,
                    "exitCode": completed.returncode,
                }
                runtime.events.append(node.run_id, "provider_rate_limited", rate_limit_payload, critical=True)
                runtime.events.append(node.run_id, "provider_blocked", {**rate_limit_payload, "detail": "provider rate limited"}, critical=True)
                return None
            self._block_node(runtime, node, "invalid_agent_result", {"exitCode": completed.returncode})
            runtime.events.append(
                node.run_id,
                "invalid_agent_result",
                {"nodeId": node.id, "agentId": profile.agent_id, "dispatchId": dispatch_id, "exitCode": completed.returncode},
                critical=True,
            )
            return None
        payload = self._result_parser.read_result_payload(workspace.final_result_path, completed.stdout or "")
        if payload is None:
            self._block_node(runtime, node, "invalid_agent_result", {"reason": "invalid_output"})
            runtime.events.append(
                node.run_id,
                "invalid_agent_result",
                {"nodeId": node.id, "agentId": profile.agent_id, "dispatchId": dispatch_id, "reason": "invalid_output"},
                critical=True,
            )
            return None
        try:
            result = AgentResult(**payload)
        except TypeError as exc:
            self._block_node(runtime, node, "invalid_agent_result", {"reason": str(exc)})
            runtime.events.append(
                node.run_id,
                "invalid_agent_result",
                {"nodeId": node.id, "agentId": profile.agent_id, "dispatchId": dispatch_id, "reason": str(exc)},
                critical=True,
            )
            return None
        if result.taskNodeId != node.id or result.agentId != profile.agent_id:
            self._block_node(runtime, node, "invalid_agent_result", {"reason": "metadata_mismatch"})
            runtime.events.append(
                node.run_id,
                "invalid_agent_result",
                {"nodeId": node.id, "agentId": profile.agent_id, "dispatchId": dispatch_id, "reason": "metadata_mismatch"},
                critical=True,
            )
            return None
        if result.workedAgainstCheckpoint != node.checkpoint_id:
            self._block_node(runtime, node, "checkpoint_mismatch", {"expected": node.checkpoint_id, "actual": result.workedAgainstCheckpoint})
            runtime.events.append(
                node.run_id,
                "checkpoint_mismatch",
                {
                    "nodeId": node.id,
                    "agentId": profile.agent_id,
                    "dispatchId": dispatch_id,
                    "expected": node.checkpoint_id,
                    "actual": result.workedAgainstCheckpoint,
                },
                critical=True,
            )
            return None
        validation = validate_agent_result(result, runtime.squad_dir / "artifacts", node.checkpoint_id)
        if not validation.valid:
            self._block_node(runtime, node, "invalid_agent_result", {"errors": validation.errors})
            runtime.events.append(
                node.run_id,
                "invalid_agent_result",
                {"nodeId": node.id, "agentId": profile.agent_id, "dispatchId": dispatch_id, "errors": validation.errors},
                critical=True,
            )
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
        runtime.events.append(
            node.run_id,
            "llm_session_completed",
            {"dispatchId": dispatch_id, "agentId": profile.agent_id, "provider": self.name, "outcome": outcome},
            critical=True,
        )
        return result

    def _block_node(self, runtime: Runtime, node, reason_code: str, metadata: dict[str, Any]) -> None:
        current = runtime.get_node(node.id)
        if current.status == NodeStatus.RUNNING:
            runtime.transition_node(node.id, NodeStatus.RUNNING, NodeStatus.BLOCKED, reason_code, blocked_reason_code=reason_code, metadata=metadata)

    def _mark_unavailable(self, runtime: Runtime, node, reason: str) -> None:
        current = runtime.get_node(node.id)
        if current.status == NodeStatus.RUNNING:
            runtime.transition_node(node.id, NodeStatus.RUNNING, NodeStatus.AGENT_UNAVAILABLE, reason)

    def rate_limit_retry_limit(self) -> int:
        return self.rate_limiter.retry_limit(self.name)


class ProviderRegistry:
    def __init__(self, providers: dict[str, Any] | None = None):
        self.providers = providers or {
            "fake_cli": FakeCliProvider(),
            "claude_cli": LocalCliProvider("claude_cli", "claude"),
            "codex_cli": LocalCliProvider("codex_cli", "codex"),
        }

    @classmethod
    def default(cls) -> ProviderRegistry:
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
