"""Lightweight provider plugin registry.

Usage::

    from squad_runtime.providers.registry import provider, list_providers

    @provider("my_custom")
    class MyProvider:
        ...

    # Later:
    cls = get_provider_class("my_custom")
"""

from __future__ import annotations

_PROVIDER_REGISTRY: dict[str, type] = {}


def provider(name: str):
    """Decorator to register a provider class by name."""

    def decorator(cls: type) -> type:
        _PROVIDER_REGISTRY[name] = cls
        return cls

    return decorator


def get_provider_class(name: str) -> type | None:
    """Retrieve a registered provider class, or None if not found."""
    return _PROVIDER_REGISTRY.get(name)


def list_providers() -> dict[str, type]:
    """Return a snapshot of all registered providers."""
    return dict(_PROVIDER_REGISTRY)


def clear_registry() -> None:
    """Reset the registry (for testing)."""
    _PROVIDER_REGISTRY.clear()
