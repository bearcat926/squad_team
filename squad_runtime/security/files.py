"""Secure file permission management."""

from __future__ import annotations

import stat
import sys
from pathlib import Path


def write_secret_file(path: Path, content: str) -> None:
    """Write a secret file with restrictive permissions (0600).

    On Windows, chmod is not effective; the file is written normally and
    the permission assertion is skipped in tests.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if sys.platform != "win32":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def check_secret_permissions(path: Path) -> bool:
    """Verify that a secret file has 0600 permissions.

    Returns True on Windows (cannot enforce POSIX permissions).
    Returns True if permissions are correctly restricted.
    Returns False if permissions are too open.
    """
    if sys.platform == "win32":
        return True
    path = Path(path)
    if not path.exists():
        return True
    mode = path.stat().st_mode
    # Check that group and other have no permissions
    return not (mode & (stat.S_IRWXG | stat.S_IRWXO))
