"""Base provider protocol and shared types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ProviderHealth:
    provider: str
    available: bool
    detail: str
    provider_type: str = "unknown"
    identity_verified: bool = False


@runtime_checkable
class BaseProvider(Protocol):
    """Protocol that all providers must implement."""

    name: str

    def health(self) -> ProviderHealth: ...

    def execute(
        self,
        runtime: Any,
        node: Any,
        profile: Any,
        synthetic: bool = False,
        provider_fallback_triggered: bool = False,
        fallback_reason: str | None = None,
    ) -> Any: ...
