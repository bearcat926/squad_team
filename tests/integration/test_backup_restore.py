"""Integration tests for the backup and restore service."""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from squad_runtime.services.backup_service import backup, restore


@pytest.fixture()
def squad_dir(tmp_path: Path) -> Path:
    """Create a realistic .squad directory structure for testing."""
    squad = tmp_path / ".squad"
    squad.mkdir()

    # Core files
    (squad / "squad.db").write_text("fake-db")
    (squad / "token").write_text("secret-token-value")

    # Subdirectories
    artifacts = squad / "artifacts"
    artifacts.mkdir()
    (artifacts / "report.json").write_text('{"result": "ok"}')

    checkpoints = squad / "checkpoints"
    checkpoints.mkdir()
    (checkpoints / "ckp-1.json").write_text('{"id": "ckp-1"}')

    runs = squad / "runs"
    runs.mkdir()
    run_dir = runs / "run-abc"
    run_dir.mkdir()
    (run_dir / "archive.json").write_text('{"run": {}}')

    return squad


# ---------------------------------------------------------------------------
# Backup basics
# ---------------------------------------------------------------------------


def test_backup_creates_valid_tar_gz(squad_dir: Path, tmp_path: Path):
    output = tmp_path / "backup.tar.gz"
    result = backup(squad_dir, output)

    assert result == output
    assert output.exists()
    assert tarfile.is_tarfile(output)


def test_backup_contains_expected_files(squad_dir: Path, tmp_path: Path):
    output = tmp_path / "backup.tar.gz"
    backup(squad_dir, output)

    with tarfile.open(output, "r:gz") as tar:
        names = set(tar.getnames())

    assert "squad.db" in names
    assert "artifacts/report.json" in names
    assert "checkpoints/ckp-1.json" in names
    assert "runs/run-abc/archive.json" in names


# ---------------------------------------------------------------------------
# Token handling
# ---------------------------------------------------------------------------


def test_backup_excludes_token_by_default(squad_dir: Path, tmp_path: Path):
    output = tmp_path / "backup.tar.gz"
    backup(squad_dir, output)

    with tarfile.open(output, "r:gz") as tar:
        names = set(tar.getnames())

    assert "token" not in names


def test_backup_includes_token_when_requested(squad_dir: Path, tmp_path: Path):
    output = tmp_path / "backup.tar.gz"
    backup(squad_dir, output, include_token=True)

    with tarfile.open(output, "r:gz") as tar:
        names = set(tar.getnames())

    assert "token" in names


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


def test_restore_extracts_to_target_directory(squad_dir: Path, tmp_path: Path):
    archive = tmp_path / "backup.tar.gz"
    backup(squad_dir, archive)

    target = tmp_path / "restored"
    result = restore(archive, target)

    assert result == target
    assert (target / "squad.db").exists()
    assert (target / "artifacts" / "report.json").exists()
    assert (target / "checkpoints" / "ckp-1.json").exists()
    assert (target / "runs" / "run-abc" / "archive.json").exists()


def test_restore_creates_target_if_missing(squad_dir: Path, tmp_path: Path):
    archive = tmp_path / "backup.tar.gz"
    backup(squad_dir, archive)

    target = tmp_path / "deep" / "nested" / "restore"
    restore(archive, target)
    assert target.is_dir()


# ---------------------------------------------------------------------------
# Round-trip: backup then restore
# ---------------------------------------------------------------------------


def test_roundtrip_produces_equivalent_directory(squad_dir: Path, tmp_path: Path):
    """Backup then restore should yield files with identical content."""
    archive = tmp_path / "backup.tar.gz"
    backup(squad_dir, archive, include_token=True)

    target = tmp_path / "restored"
    restore(archive, target)

    # Compare every file that was in the original (excluding directories).
    for root, _dirs, files in squad_dir.walk():
        for filename in files:
            original = Path(root) / filename
            relative = original.relative_to(squad_dir)
            restored_file = target / relative
            assert restored_file.exists(), f"Missing after restore: {relative}"
            assert restored_file.read_bytes() == original.read_bytes(), f"Content mismatch: {relative}"


def test_roundtrip_without_token(squad_dir: Path, tmp_path: Path):
    """Round-trip without token: restored dir has everything except token."""
    archive = tmp_path / "backup.tar.gz"
    backup(squad_dir, archive, include_token=False)

    target = tmp_path / "restored"
    restore(archive, target)

    assert (target / "squad.db").exists()
    assert not (target / "token").exists()
    assert (target / "artifacts" / "report.json").exists()


def test_backup_output_path_parent_created(squad_dir: Path, tmp_path: Path):
    """Output directory is created if it doesn't exist."""
    output = tmp_path / "nested" / "dir" / "backup.tar.gz"
    backup(squad_dir, output)
    assert output.exists()


def test_backup_empty_squad_dir(tmp_path: Path):
    """Backup of an empty .squad directory should still produce a valid archive."""
    empty_squad = tmp_path / ".squad"
    empty_squad.mkdir()

    output = tmp_path / "backup.tar.gz"
    backup(empty_squad, output)

    assert output.exists()
    assert tarfile.is_tarfile(output)
