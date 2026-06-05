"""Provider environment variable isolation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Variables that are always safe to pass through
BASE_ALLOWED_ENV: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "COMSPEC",
        "PATHEXT",
        "USERPROFILE",
        "LANG",
        "LC_ALL",
        "TERM",
    }
)

# Prefixes that are blocked by default (cloud/DB/secret related)
BLOCKED_PREFIXES: tuple[str, ...] = (
    "AWS_",
    "AZURE_",
    "GCP_",
    "GOOGLE_",
    "DATABASE_",
    "POSTGRES_",
    "MYSQL_",
    "SECRET_",
    "TOKEN_",
)

# Prefix that is always allowed (Squad-specific)
_SQUAD_PREFIX = "SQUAD_"


@dataclass(frozen=True)
class ProviderConfig:
    """Declaration of environment variables a provider requires."""

    name: str
    required_env: list[str] = field(default_factory=list)


def build_provider_env(
    provider_config: ProviderConfig,
    host_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a safe environment dict for a provider subprocess.

    Rules:
    1. Always include BASE_ALLOWED_ENV variables.
    2. Always include SQUAD_* variables.
    3. Include variables explicitly listed in ``provider_config.required_env``.
    4. Everything else is stripped.
    """
    if host_env is None:
        host_env = dict(os.environ)

    safe_env: dict[str, str] = {}

    required_set = set(provider_config.required_env)

    for key, value in host_env.items():
        upper_key = key.upper()

        # Always allow base env
        if key in BASE_ALLOWED_ENV:
            safe_env[key] = value
            continue

        # Always allow SQUAD_*
        if upper_key.startswith(_SQUAD_PREFIX):
            safe_env[key] = value
            continue

        # Allow provider-declared required vars
        if key in required_set:
            safe_env[key] = value
            continue

        # Block everything else (implicitly)

    return safe_env
