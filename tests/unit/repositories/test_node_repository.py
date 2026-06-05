"""Unit tests for NodeRepository."""

from __future__ import annotations

from pathlib import Path

import pytest

from squad_runtime.infrastructure.database import Database
from squad_runtime.infrastructure.schema import init_schema
from squad_runtime.repositories.node_repository import NodeRepository
from squad_runtime.state import NodeStatus


@pytest.fixture()
def repo(tmp_path: Path) -> NodeRepository:
    db = Database(tmp_path / "test.db")
    init_schema(db.conn)
    return NodeRepository(db.conn)


def test_insert_and_get(repo: NodeRepository):
    repo.insert("node-1", "run-1", "Build UI", "frontend", "frontend-dev", NodeStatus.TODO, "ckp-1")
    node = repo.get("node-1")
    assert node.id == "node-1"
    assert node.run_id == "run-1"
    assert node.title == "Build UI"
    assert node.status == NodeStatus.TODO


def test_get_missing_raises_key_error(repo: NodeRepository):
    with pytest.raises(KeyError):
        repo.get("nonexistent")


def test_list_by_run(repo: NodeRepository):
    repo.insert("node-1", "run-1", "Task A", "backend", "backend-dev", NodeStatus.TODO, "ckp-1")
    repo.insert("node-2", "run-1", "Task B", "frontend", "frontend-dev", NodeStatus.TODO, "ckp-1")
    repo.insert("node-3", "run-2", "Task C", "test", "test-dev", NodeStatus.TODO, "ckp-1")
    nodes = repo.list_by_run("run-1")
    assert len(nodes) == 2
    assert all(n.run_id == "run-1" for n in nodes)


def test_update_status(repo: NodeRepository):
    repo.insert("node-1", "run-1", "Task", "backend", "backend-dev", NodeStatus.TODO, "ckp-1")
    repo.update_status("node-1", NodeStatus.TODO, NodeStatus.READY, None)
    node = repo.get("node-1")
    assert node.status == NodeStatus.READY


def test_update_status_with_blocked_reason(repo: NodeRepository):
    repo.insert("node-1", "run-1", "Task", "backend", "backend-dev", NodeStatus.TODO, "ckp-1")
    repo.update_status("node-1", NodeStatus.TODO, NodeStatus.BLOCKED, "missing_test_pass")
    node = repo.get("node-1")
    assert node.status == NodeStatus.BLOCKED
    assert node.blocked_reason_code == "missing_test_pass"


def test_list_by_status(repo: NodeRepository):
    repo.insert("node-1", "run-1", "Task A", "backend", "backend-dev", NodeStatus.RUNNING, "ckp-1")
    repo.insert("node-2", "run-1", "Task B", "frontend", "frontend-dev", NodeStatus.TODO, "ckp-1")
    running = repo.list_by_status(NodeStatus.RUNNING)
    assert len(running) == 1
    assert running[0].id == "node-1"
