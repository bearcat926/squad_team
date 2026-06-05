from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path


EXCLUDED_DIRS = {".git", ".squad", "__pycache__", "node_modules", "dist", "build", ".pytest_cache", ".mypy_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".sqlite", ".db", ".wal", ".shm"}


@dataclass(frozen=True)
class Checkpoint:
    checkpoint_id: str
    mode: str
    manifest_path: Path


class CheckpointManager:
    def __init__(self, project_dir: Path, squad_dir: Path):
        self.project_dir = Path(project_dir)
        self.squad_dir = Path(squad_dir)
        (self.squad_dir / "checkpoints").mkdir(parents=True, exist_ok=True)

    def create_snapshot_checkpoint(self) -> Checkpoint:
        files = []
        for path in sorted(self.project_dir.rglob("*")):
            if not path.is_file() or self._excluded(path):
                continue
            rel = path.relative_to(self.project_dir).as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            files.append({"path": rel, "sha256": digest})
        manifest_seed = json.dumps({"files": files}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        checkpoint_id = "ckp-" + hashlib.sha256(manifest_seed.encode("utf-8")).hexdigest()[:24]
        checkpoint_dir = self.squad_dir / "checkpoints" / checkpoint_id
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        for item in files:
            source = self.project_dir / item["path"]
            target = checkpoint_dir / "snapshot" / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        manifest_path = checkpoint_dir / "manifest.json"
        manifest_path.write_text(json.dumps({"mode": "snapshot", "checkpointId": checkpoint_id, "files": files}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return Checkpoint(checkpoint_id=checkpoint_id, mode="snapshot", manifest_path=manifest_path)

    def _excluded(self, path: Path) -> bool:
        rel_parts = path.relative_to(self.project_dir).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts):
            return True
        return path.suffix.lower() in EXCLUDED_SUFFIXES
