from __future__ import annotations

import hashlib
import json
import shutil
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .security.paths import UnsafePathError, validate_path_within_root

EXCLUDED_DIRS = {".git", ".squad", "__pycache__", "node_modules", "dist", "build", ".pytest_cache", ".mypy_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".sqlite", ".db", ".wal", ".shm"}


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    manifest_path: Path
    snapshot_dir: Path


class SnapshotManager:
    """Creates content-addressed workspace snapshots with canonical manifests."""

    def __init__(self, workspace_root: Path, squad_dir: Path):
        self.workspace_root = Path(workspace_root).resolve()
        self.squad_dir = Path(squad_dir)
        (self.squad_dir / "checkpoints").mkdir(parents=True, exist_ok=True)

    def seal_snapshot(self, include: Iterable[str | Path] | None = None) -> Snapshot:
        files = self._collect_files(include)
        manifest_hash_input: dict[str, Any] = {
            "schemaVersion": "snapshot-manifest/v1",
            "boundaryPolicy": self._boundary_policy(),
            "symlinkPolicy": self._symlink_policy(),
            "environmentFingerprintRef": "env:fingerprint-pending",
            "files": files,
        }
        snapshot_hash = hashlib.sha256(self._canonical_json(manifest_hash_input).encode("utf-8")).hexdigest()
        snapshot_id = f"snap-{snapshot_hash}"
        snapshot_dir = self.squad_dir / "checkpoints" / snapshot_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._copy_files(files, snapshot_dir / "snapshot")
        manifest = {
            **manifest_hash_input,
            "snapshotHash": snapshot_hash,
            "metadata": {
                "createdAt": datetime.now(UTC).isoformat(),
                "fileCount": len(files),
                "totalBytes": sum(int(item["sizeBytes"]) for item in files),
            },
        }
        manifest_path = snapshot_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return Snapshot(snapshot_id=snapshot_id, manifest_path=manifest_path, snapshot_dir=snapshot_dir)

    def _collect_files(self, include: Iterable[str | Path] | None) -> list[dict[str, Any]]:
        paths = self._included_paths(include)
        files: list[dict[str, object]] = []
        for path in paths:
            if self._excluded(path):
                continue
            if path.is_symlink():
                self._validate_symlink(path)
            if not path.is_file():
                continue
            rel = self._canonical_relative_path(path)
            canonical_content = self._canonical_file_bytes(path)
            files.append(
                {
                    "path": rel,
                    "contentHash": f"sha256:{hashlib.sha256(canonical_content).hexdigest()}",
                    "sizeBytes": len(canonical_content),
                }
            )
        return sorted(files, key=lambda item: str(item["path"]))

    def _included_paths(self, include: Iterable[str | Path] | None) -> list[Path]:
        if include is None:
            return sorted(self.workspace_root.rglob("*"))
        paths: list[Path] = []
        for item in include:
            resolved = validate_path_within_root(item, self.workspace_root)
            if resolved.is_dir():
                paths.extend(sorted(resolved.rglob("*")))
            else:
                paths.append(resolved)
        return paths

    def _excluded(self, path: Path) -> bool:
        rel_parts = path.relative_to(self.workspace_root).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts):
            return True
        return path.suffix.lower() in EXCLUDED_SUFFIXES

    def _validate_symlink(self, path: Path) -> None:
        target = path.resolve()
        try:
            target.relative_to(self.workspace_root)
        except ValueError as err:
            raise UnsafePathError(f"Symlink escapes root: {path} -> {target}") from err

    def _canonical_relative_path(self, path: Path) -> str:
        relative = path.relative_to(self.workspace_root).as_posix()
        return unicodedata.normalize("NFC", relative)

    def _canonical_file_bytes(self, path: Path) -> bytes:
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw
        normalized = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
        return normalized.encode("utf-8")

    def _copy_files(self, files: list[dict[str, Any]], target_root: Path) -> None:
        for item in files:
            rel = str(item["path"])
            source = validate_path_within_root(rel, self.workspace_root)
            target = target_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def _boundary_policy(self) -> dict[str, str]:
        return {
            "mode": "workspace-root-only",
            "workspaceRoot": str(self.workspace_root),
            "deniedRoots": ".git,.squad,node_modules,dist,build",
        }

    @staticmethod
    def _symlink_policy() -> dict[str, str]:
        return {"mode": "deny-external"}

    @staticmethod
    def _canonical_json(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
