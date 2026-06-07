from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from squad_runtime.agent_contracts import AgentResult
from squad_runtime.agent_registry import AgentRegistry
from squad_runtime.context import AgentContextBuilder
from squad_runtime.runtime import Runtime
from squad_runtime.security.paths import UnsafePathError
from squad_runtime.snapshot import SnapshotManager


def test_snapshot_manifest_is_canonical_and_reproducible(tmp_path: Path) -> None:
    project = tmp_path / "project"
    squad = project / ".squad"
    project.mkdir()
    (project / "b.txt").write_bytes(b"hello\r\nworld\r\n")
    (project / "nested").mkdir()
    (project / "nested" / "a.txt").write_text("cafe\u0301\n", encoding="utf-8")
    (project / "node_modules").mkdir()
    (project / "node_modules" / "ignored.txt").write_text("ignore-v1", encoding="utf-8")

    manager = SnapshotManager(project, squad)
    first = manager.seal_snapshot()
    second = manager.seal_snapshot()

    assert first.snapshot_id == second.snapshot_id
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schemaVersion"] == "snapshot-manifest/v1"
    assert manifest["snapshotHash"] == first.snapshot_id.removeprefix("snap-")
    assert manifest["boundaryPolicy"]["workspaceRoot"].endswith("project")
    assert manifest["symlinkPolicy"]["mode"] == "deny-external"
    assert manifest["environmentFingerprintRef"] == "env:fingerprint-pending"
    assert [item["path"] for item in manifest["files"]] == ["b.txt", "nested/a.txt"]
    assert all("\\" not in item["path"] for item in manifest["files"])
    assert all(item["contentHash"].startswith("sha256:") for item in manifest["files"])
    assert manifest["metadata"]["fileCount"] == 2

    (project / "node_modules" / "ignored.txt").write_text("ignore-v2", encoding="utf-8")
    assert manager.seal_snapshot().snapshot_id == first.snapshot_id

    (project / "b.txt").write_bytes(b"hello\nworld\n")
    assert manager.seal_snapshot().snapshot_id == first.snapshot_id

    (project / "b.txt").write_text("changed\n", encoding="utf-8")
    assert manager.seal_snapshot().snapshot_id != first.snapshot_id


def test_snapshot_rejects_path_traversal_include(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(UnsafePathError):
        SnapshotManager(project, project / ".squad").seal_snapshot(include=["../secret.txt"])


def test_agent_context_and_result_expose_snapshot_metadata(tmp_path: Path) -> None:
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("snapshot metadata")
    node = runtime.create_node(run.id, "Build", "frontend", "frontend-developer", checkpoint_id="snap-base")

    context = AgentContextBuilder(runtime, AgentRegistry.default()).build(node.id)
    result = AgentResult(
        taskNodeId=node.id,
        agentId="frontend-developer",
        status="pass",
        summary="done",
        evidence=[],
        artifacts=[],
        risks=[],
        nextActions=[],
        confidence=0.9,
        workedAgainstCheckpoint="snap-base",
        agentContractVersion="v1",
    )

    assert context.base_snapshot_id == "snap-base"
    assert context.result_snapshot_id is None
    assert result.schemaVersion == "agent-result/v1"
    assert result.baseSnapshotId == "snap-base"
    assert result.resultSnapshotId is None


@pytest.mark.skipif(sys.platform == "win32", reason="Symlinks require elevated privileges on Windows")
def test_snapshot_rejects_external_symlink(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    (project / "link.txt").symlink_to(outside)

    with pytest.raises(UnsafePathError):
        SnapshotManager(project, project / ".squad").seal_snapshot()
