from __future__ import annotations

from pathlib import Path

from .agent_registry import AgentRegistry
from .providers import ProviderRegistry
from .runtime import Runtime


class AgentRuntimeAdapter:
    def __init__(self, runtime: Runtime, registry: AgentRegistry, providers: ProviderRegistry):
        self.runtime = runtime
        self.registry = registry
        self.providers = providers

    def dispatch_once(self, node_id: str, provider_override: str | None = None):
        node = self.runtime.get_node(node_id)
        profile = self.registry.get(node.owner_agent_id)
        provider_name = provider_override or profile.provider
        provider = self.providers.get(provider_name)
        try:
            return provider.execute(self.runtime, node, profile)
        except Exception as exc:
            if profile.fallback_provider and profile.fallback_mode == "automatic":
                self.runtime.events.append(
                    node.run_id,
                    "provider_fallback_triggered",
                    {
                        "nodeId": node.id,
                        "agentId": profile.agent_id,
                        "primaryProvider": provider_name,
                        "fallbackProvider": profile.fallback_provider,
                        "reason": "primary_provider_unavailable",
                        "detail": str(exc),
                    },
                    critical=True,
                )
                fallback = self.providers.get(profile.fallback_provider)
                return fallback.execute(
                    self.runtime,
                    node,
                    profile,
                    provider_fallback_triggered=True,
                    fallback_reason="primary_provider_unavailable",
                )
            raise

    def validate_file_access(self, node_id: str, path: Path, mode: str) -> bool:
        node = self.runtime.get_node(node_id)
        normalized = Path(path).as_posix().lower()
        denied = "/.squad/" in normalized or normalized.endswith("/.squad") or ".squad/" in normalized
        if denied:
            self.runtime.events.append(
                node.run_id,
                "tool_permission_denied",
                {"nodeId": node.id, "agentId": node.owner_agent_id, "path": str(path), "mode": mode, "reason": "forbidden_squad_path"},
                critical=True,
            )
            return False
        return True
