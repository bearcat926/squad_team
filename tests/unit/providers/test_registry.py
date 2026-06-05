"""Tests for the provider plugin registry."""

from __future__ import annotations

from squad_runtime.providers.registry import (
    clear_registry,
    get_provider_class,
    list_providers,
    provider,
)


class TestProviderRegistry:
    def setup_method(self):
        clear_registry()

    def teardown_method(self):
        clear_registry()

    def test_register_and_retrieve(self):
        @provider("test_provider")
        class TestProv:
            pass

        assert get_provider_class("test_provider") is TestProv

    def test_unknown_provider_returns_none(self):
        assert get_provider_class("nonexistent") is None

    def test_list_providers(self):
        @provider("alpha")
        class Alpha:
            pass

        @provider("beta")
        class Beta:
            pass

        providers = list_providers()
        assert "alpha" in providers
        assert "beta" in providers
        assert len(providers) == 2

    def test_clear_registry(self):
        @provider("temp")
        class Temp:
            pass

        clear_registry()
        assert list_providers() == {}
