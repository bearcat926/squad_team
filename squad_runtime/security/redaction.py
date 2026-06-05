"""Sensitive data redaction for events and exports."""

from __future__ import annotations

import re

# Patterns to detect and redact sensitive values
_SENSITIVE_PATTERNS: list[re.Pattern[str]] = [
    # API keys with common prefixes
    re.compile(r"(sk-[a-zA-Z0-9]{20,})", re.IGNORECASE),
    re.compile(r"(AKIA[0-9A-Z]{16})", re.IGNORECASE),
    # Bearer / Authorization tokens
    re.compile(r"((?:Bearer|bearer)\s+[a-zA-Z0-9._\-]{20,})", re.IGNORECASE),
    # JWT-like tokens (three dot-separated base64 segments)
    re.compile(r"(eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)", re.IGNORECASE),
    # GitHub tokens (ghp_, gho_, ghs_, ghr_)
    re.compile(r"(gh[psor]_[a-zA-Z0-9]{20,})", re.IGNORECASE),
]

# Field names whose values should always be redacted
_SENSITIVE_KEYS = frozenset(
    {
        "token",
        "password",
        "secret",
        "api_key",
        "apikey",
        "authorization",
        "access_token",
        "refresh_token",
        "private_key",
        "client_secret",
    }
)

_REDACTED = "***REDACTED***"


def redact_text(text: str) -> str:
    """Redact sensitive patterns found in free-form text."""
    result = text
    for pattern in _SENSITIVE_PATTERNS:
        result = pattern.sub(_REDACTED, result)
    return result


def redact_dict(data: dict[str, object]) -> dict[str, object]:
    """Return a shallow copy of *data* with sensitive values redacted.

    Keys matching ``_SENSITIVE_KEYS`` (case-insensitive) are replaced.
    String values are also scanned for embedded sensitive patterns.
    """
    out: dict[str, object] = {}
    for key, value in data.items():
        if key.lower() in _SENSITIVE_KEYS:
            out[key] = _REDACTED
        elif isinstance(value, str):
            out[key] = redact_text(value)
        elif isinstance(value, dict):
            out[key] = redact_dict(value)
        else:
            out[key] = value
    return out
