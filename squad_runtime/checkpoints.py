from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .snapshot import SnapshotManager


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
        snapshot = SnapshotManager(self.project_dir, self.squad_dir).seal_snapshot()
        manifest = json.loads(snapshot.manifest_path.read_text(encoding="utf-8"))
        legacy_files = [{"path": item["path"], "sha256": str(item["contentHash"]).removeprefix("sha256:")} for item in manifest["files"]]
        manifest["mode"] = "snapshot"
        manifest["checkpointId"] = snapshot.snapshot_id
        manifest["files"] = [{**item, "sha256": item["contentHash"].removeprefix("sha256:")} for item in manifest["files"]]
        snapshot.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        # Retain the legacy file shape used by existing tests while preserving
        # the richer manifest fields for Phase 2.
        if legacy_files:
            manifest["files"] = legacy_files
        return Checkpoint(checkpoint_id=snapshot.snapshot_id, mode="snapshot", manifest_path=snapshot.manifest_path)
