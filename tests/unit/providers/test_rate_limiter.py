from __future__ import annotations

from squad_runtime.providers.rate_limiter import ProviderRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_rate_limiter_waits_for_claude_min_interval(monkeypatch):
    monkeypatch.setenv("SQUAD_CLAUDE_CLI_MIN_INTERVAL_SEC", "30")
    clock = FakeClock()
    limiter = ProviderRateLimiter.from_env(clock=clock.monotonic, sleeper=clock.sleep)

    first = limiter.wait_before_dispatch("claude_cli")
    clock.now += 5
    second = limiter.wait_before_dispatch("claude_cli")

    assert first.waited_seconds == 0
    assert second.waited_seconds == 25
    assert clock.sleeps == [25]


def test_rate_limiter_does_not_wait_for_fake_cli(monkeypatch):
    monkeypatch.setenv("SQUAD_CLAUDE_CLI_MIN_INTERVAL_SEC", "30")
    clock = FakeClock()
    limiter = ProviderRateLimiter.from_env(clock=clock.monotonic, sleeper=clock.sleep)

    limiter.wait_before_dispatch("fake_cli")
    limiter.wait_before_dispatch("fake_cli")

    assert clock.sleeps == []


def test_rate_limiter_applies_429_and_529_cooldowns(monkeypatch):
    monkeypatch.setenv("SQUAD_CLAUDE_CLI_COOLDOWN_429_SEC", "180")
    monkeypatch.setenv("SQUAD_CLAUDE_CLI_COOLDOWN_529_SEC", "60")
    clock = FakeClock()
    limiter = ProviderRateLimiter.from_env(clock=clock.monotonic, sleeper=clock.sleep)

    limit_429 = limiter.record_provider_error("claude_cli", "API Error: Request rejected (429)")
    wait_429 = limiter.wait_before_dispatch("claude_cli")
    limit_529 = limiter.record_provider_error("claude_cli", "API Error: Repeated 529 Overloaded errors")
    wait_529 = limiter.wait_before_dispatch("claude_cli")

    assert limit_429.is_rate_limited is True
    assert limit_429.status_code == 429
    assert wait_429.waited_seconds == 180
    assert limit_529.is_rate_limited is True
    assert limit_529.status_code == 529
    assert wait_529.waited_seconds == 60


def test_rate_limiter_ignores_non_rate_limit_errors():
    limiter = ProviderRateLimiter.from_env()

    signal = limiter.record_provider_error("claude_cli", "syntax error in provider script")

    assert signal.is_rate_limited is False
