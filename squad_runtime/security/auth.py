"""API authentication enforcement."""

from __future__ import annotations

import secrets
from pathlib import Path

from ..security import read_token


def token_matches(squad_dir: Path, provided: str | None) -> bool:
    """Check whether the provided token matches the stored token.

    Returns False if no token is provided or if the token file does not exist.
    Uses constant-time comparison to prevent timing attacks.
    """
    if not provided:
        return False
    try:
        expected = read_token(squad_dir)
    except FileNotFoundError:
        return False
    return secrets.compare_digest(expected, provided)
