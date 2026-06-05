"""Tests for file permission security."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from squad_runtime.security import initialize_project
from squad_runtime.security.files import check_secret_permissions, write_secret_file


def test_write_secret_file_creates_file(tmp_path: Path):
    secret_path = tmp_path / "subdir" / "secret.txt"
    write_secret_file(secret_path, "my-secret-value")

    assert secret_path.exists()
    assert secret_path.read_text(encoding="utf-8") == "my-secret-value"


def test_token_file_permissions_after_init(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    initialize_project(squad_dir)

    token_path = squad_dir / "token"
    assert token_path.exists()
    assert check_secret_permissions(token_path) is True


def test_check_secret_permissions_returns_true_on_windows(tmp_path: Path):
    """On Windows, permission check always returns True."""
    if sys.platform != "win32":
        return  # Skip on non-Windows
    secret_path = tmp_path / "secret.txt"
    secret_path.write_text("test", encoding="utf-8")
    assert check_secret_permissions(secret_path) is True


def test_check_secret_permissions_on_missing_file(tmp_path: Path):
    assert check_secret_permissions(tmp_path / "nonexistent") is True


def test_check_secret_permissions_too_open_on_posix(tmp_path: Path):
    """On POSIX, files with group/other permissions should return False."""
    if sys.platform == "win32":
        pytest.skip("POSIX-only test")
    secret_path = tmp_path / "open-secret.txt"
    secret_path.write_text("test", encoding="utf-8")
    secret_path.chmod(0o644)
    # 先断言确实制造了"过宽权限"，避免 umask 干扰
    assert secret_path.stat().st_mode & 0o077, "expected group/other bits to be set"
    assert check_secret_permissions(secret_path) is False
