"""Tests for path safety enforcement."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from squad_runtime.security.paths import UnsafePathError, validate_path_within_root


def test_relative_path_inside_root(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()

    result = validate_path_within_root("docs/readme.md", root)

    assert result == (root / "docs" / "readme.md").resolve()


def test_dotdot_escape_rejected(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()

    with pytest.raises(UnsafePathError, match="escapes root"):
        validate_path_within_root("../escape.txt", root)


def test_absolute_path_outside_root_rejected(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.txt"

    with pytest.raises(UnsafePathError, match="escapes root"):
        validate_path_within_root(str(outside), root)


def test_unc_path_rejected(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()

    with pytest.raises(UnsafePathError, match="UNC"):
        validate_path_within_root(r"\\server\share\file.txt", root)


def test_windows_reserved_name_rejected(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()

    for name in ["CON", "NUL", "PRN", "AUX", "COM1", "LPT9"]:
        with pytest.raises(UnsafePathError, match="reserved"):
            validate_path_within_root(name, root)


@pytest.mark.skipif(sys.platform == "win32", reason="Symlinks require admin on Windows")
def test_symlink_escape_rejected(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link = root / "link.txt"
    link.symlink_to(outside)

    with pytest.raises(UnsafePathError, match="Symlink"):
        validate_path_within_root("link.txt", root)


@pytest.mark.skipif(sys.platform == "win32", reason="Symlinks require admin on Windows")
def test_symlink_inside_root_allowed(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    target = root / "real.txt"
    target.write_text("data", encoding="utf-8")
    link = root / "link.txt"
    link.symlink_to(target)

    result = validate_path_within_root("link.txt", root)

    assert result.exists()
