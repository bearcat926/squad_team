"""Path safety enforcement to prevent traversal and escape attacks."""

from __future__ import annotations

import re
from pathlib import Path

_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

_UNC_PREFIX_RE = re.compile(r"^\\\\[^?\\]")


class UnsafePathError(ValueError):
    """Raised when a path fails safety checks."""


def validate_path_within_root(path: str | Path, root: Path) -> Path:
    """Ensure that *path* resolves inside *root* after normalization.

    Checks performed:
    - No ``..`` components that escape *root*.
    - No absolute path that points outside *root*.
    - No Windows reserved names (CON, NUL, etc.).
    - No UNC paths (\\\\server\\share).
    - If *path* is a symlink, the link target must also be inside *root*.

    Returns the resolved ``Path`` relative to *root*.
    Raises ``UnsafePathError`` if any check fails.
    """
    root = root.resolve()
    candidate = Path(path)

    # Reject UNC paths
    raw = str(candidate)
    if _UNC_PREFIX_RE.match(raw):
        raise UnsafePathError(f"UNC path not allowed: {raw}")

    # Reject Windows reserved names in any component
    for part in candidate.parts:
        if part.upper() in _WINDOWS_RESERVED:
            raise UnsafePathError(f"Windows reserved name: {part}")

    # Resolve relative to root
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()

    # Must be inside root
    try:
        resolved.relative_to(root)
    except ValueError as err:
        raise UnsafePathError(f"Path escapes root: {path} (resolved: {resolved})") from err

    # Symlink check
    if resolved.is_symlink():
        link_target = resolved.readlink().resolve()
        try:
            link_target.relative_to(root)
        except ValueError as err:
            raise UnsafePathError(f"Symlink escapes root: {path} -> {link_target}") from err

    return resolved
