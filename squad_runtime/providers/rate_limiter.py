"""Provider-level rate limiting helpers."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderRateLimitConfig:
    min_interval_seconds: float
    cooldown_429_seconds: float
    cooldown_529_seconds: float
    max_rate_limit_retries: int


@dataclass(frozen=True)
class ProviderRateLimitWait:
    provider: str
    waited_seconds: float
    reason: str | None = None


@dataclass(frozen=True)
class ProviderRateLimitSignal:
    provider: str
    is_rate_limited: bool
    status_code: int | None = None
    cooldown_seconds: float = 0.0
    reason: str | None = None


class ProviderRateLimiter:
    """In-memory limiter for single-instance provider dispatch pacing."""

    def __init__(
        self,
        configs: dict[str, ProviderRateLimitConfig],
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.configs = configs
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or time.sleep
        self._last_dispatch_at: dict[str, float] = {}
        self._cooldown_until: dict[str, float] = {}

    @classmethod
    def from_env(
        cls,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> ProviderRateLimiter:
        return cls(
            {
                "claude_cli": ProviderRateLimitConfig(
                    min_interval_seconds=_env_float("SQUAD_CLAUDE_CLI_MIN_INTERVAL_SEC", 30.0),
                    cooldown_429_seconds=_env_float("SQUAD_CLAUDE_CLI_COOLDOWN_429_SEC", 30.0),
                    cooldown_529_seconds=_env_float("SQUAD_CLAUDE_CLI_COOLDOWN_529_SEC", 30.0),
                    max_rate_limit_retries=_env_int("SQUAD_CLAUDE_CLI_RATE_LIMIT_RETRIES", 1),
                )
            },
            clock=clock,
            sleeper=sleeper,
        )

    def wait_before_dispatch(self, provider: str) -> ProviderRateLimitWait:
        config = self.configs.get(provider)
        if config is None:
            return ProviderRateLimitWait(provider, 0.0)
        now = self._clock()
        min_interval_until = self._last_dispatch_at[provider] + config.min_interval_seconds if provider in self._last_dispatch_at else now
        cooldown_until = self._cooldown_until.get(provider, now)
        wait_until = max(min_interval_until, cooldown_until)
        wait_seconds = max(wait_until - now, 0.0)
        reason = None
        if wait_seconds > 0:
            reason = "cooldown" if cooldown_until >= min_interval_until else "min_interval"
            self._sleeper(wait_seconds)
            now = self._clock()
        self._last_dispatch_at[provider] = now
        return ProviderRateLimitWait(provider, wait_seconds, reason)

    def record_provider_error(self, provider: str, output: str) -> ProviderRateLimitSignal:
        config = self.configs.get(provider)
        if config is None:
            return ProviderRateLimitSignal(provider, False)
        normalized = output.lower()
        status_code: int | None = None
        cooldown_seconds = 0.0
        reason: str | None = None
        if "429" in normalized or "rate limit" in normalized or "rate_limit" in normalized or "temporarily limiting requests" in normalized:
            status_code = 429
            cooldown_seconds = config.cooldown_429_seconds
            reason = "rate_limit"
        elif "529" in normalized or "overloaded" in normalized:
            status_code = 529
            cooldown_seconds = config.cooldown_529_seconds
            reason = "overloaded"
        if status_code is None:
            return ProviderRateLimitSignal(provider, False)
        self._cooldown_until[provider] = max(self._cooldown_until.get(provider, 0.0), self._clock() + cooldown_seconds)
        return ProviderRateLimitSignal(provider, True, status_code, cooldown_seconds, reason)

    def retry_limit(self, provider: str) -> int:
        config = self.configs.get(provider)
        return config.max_rate_limit_retries if config is not None else 0


def _env_float(name: str, default: float) -> float:
    try:
        return max(float(os.environ.get(name, str(default))), 0.0)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return max(int(os.environ.get(name, str(default))), 0)
    except ValueError:
        return default
