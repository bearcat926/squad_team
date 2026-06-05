"""Unit tests for the BaseProvider protocol."""

from __future__ import annotations

from squad_runtime.providers.base import BaseProvider, ProviderHealth


def test_provider_health_is_frozen_dataclass():
    health = ProviderHealth("test", True, "ok", "deterministic", True)
    assert health.provider == "test"
    assert health.available is True
    assert health.detail == "ok"
    assert health.provider_type == "deterministic"
    assert health.identity_verified is True


def test_provider_health_default_values():
    health = ProviderHealth("test", False, "down")
    assert health.provider_type == "unknown"
    assert health.identity_verified is False


def test_base_provider_protocol_is_runtime_checkable():
    class ValidProvider:
        name = "valid"

        def health(self):
            return ProviderHealth(self.name, True, "ok")

        def execute(self, runtime, node, profile, **kwargs):
            return None

    assert isinstance(ValidProvider(), BaseProvider)


def test_base_provider_protocol_rejects_incomplete():
    class Incomplete:
        name = "incomplete"

    assert not isinstance(Incomplete(), BaseProvider)
