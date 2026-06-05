"""Unit tests for security.auth re-export + security.__init__ core paths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from squad_runtime.security import (
    initialize_project,
    read_token,
    rotate_token,
    token_matches,
)
from squad_runtime.security.auth import token_matches as auth_token_matches

# ── re-export ───────────────────────────────────────────


def test_auth_re_exports_token_matches():
    """auth.token_matches is the same object as security.token_matches."""
    assert auth_token_matches is token_matches


# ── token_matches ───────────────────────────────────────


def test_token_matches_file_not_found(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    squad_dir.mkdir(parents=True, exist_ok=True)
    assert token_matches(squad_dir, "any-token") is False


def test_token_matches_none_provided(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    initialize_project(squad_dir)
    assert token_matches(squad_dir, None) is False


def test_token_matches_empty_string(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    initialize_project(squad_dir)
    assert token_matches(squad_dir, "") is False


def test_token_matches_correct(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    result = initialize_project(squad_dir)
    assert token_matches(squad_dir, result.token) is True


def test_token_matches_wrong(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    initialize_project(squad_dir)
    assert token_matches(squad_dir, "definitely-wrong-token") is False


def test_token_matches_uses_constant_time_comparison(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    result = initialize_project(squad_dir)
    with patch("secrets.compare_digest", return_value=True) as mock_cmp:
        assert token_matches(squad_dir, result.token) is True
        mock_cmp.assert_called_once_with(result.token, result.token)


# ── read_token ──────────────────────────────────────────


def test_read_token_file_not_found(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    squad_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(FileNotFoundError, match="Missing squad token"):
        read_token(squad_dir)


# ── initialize_project 已有 token ─────────────────────────


def test_initialize_project_existing_token_does_not_rotate(tmp_path: Path):
    """Second initialization should return the same token without rotation."""
    squad_dir = tmp_path / ".squad"
    first = initialize_project(squad_dir)
    second = initialize_project(squad_dir)
    assert second.token == first.token
    assert second.token_created is False


# ── rotate_token ──────────────────────────────────────────


def test_rotate_token_replaces_existing_token(tmp_path: Path):
    """rotate_token should generate a new token and persist it."""
    squad_dir = tmp_path / ".squad"
    result = initialize_project(squad_dir)
    old_token = result.token
    assert result.token_created is True

    new_token = rotate_token(squad_dir)
    assert new_token != old_token
    assert read_token(squad_dir) == new_token

    # Verify old token no longer matches
    assert token_matches(squad_dir, old_token) is False
    assert token_matches(squad_dir, new_token) is True
