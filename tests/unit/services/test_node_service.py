"""Unit tests for NodeService."""

from __future__ import annotations

from pathlib import Path

import pytest

from squad_runtime.event_store import EventStore
from squad_runtime.infrastructure.database import Database
from squad_runtime.infrastructure.schema import init_schema
from squad_runtime.repositories.node_repository import NodeRepository
from squad_runtime.repositories.run_repository import RunRepository
from squad_runtime.services.node_service import NodeService
from squad_runtime.services.run_service import RunService
from squad_runtime.state import InvalidTransition, NodeStatus


@pytest.fixture()
def setup(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    init_schema(db.conn)
    events = EventStore(tmp_path / ".squad")
    run_repo = RunRepository(db.conn)
    node_repo = NodeRepository(db.conn)
    run_service = RunService(run_repo, events)
    node_service = NodeService(node_repo, run_repo, events)
    run = run_service.create_run("test goal")
    return node_service, run


def test_create_node(setup):
    node_service, run = setup
    node = node_service.create_node(run.id, "Build UI", "frontend", "frontend-dev")
    assert node.title == "Build UI"
    assert node.status == NodeStatus.TODO
    assert node.id.startswith("node-")


def test_get_node(setup):
    node_service, run = setup
    created = node_service.create_node(run.id, "Task", "backend", "backend-dev")
    retrieved = node_service.get_node(created.id)
    assert retrieved.id == created.id


def test_list_nodes(setup):
    node_service, run = setup
    node_service.create_node(run.id, "Task A", "backend", "backend-dev")
    node_service.create_node(run.id, "Task B", "frontend", "frontend-dev")
    nodes = node_service.list_nodes(run.id)
    assert len(nodes) == 2


def test_transition_node(setup):
    node_service, run = setup
    node = node_service.create_node(run.id, "Task", "backend", "backend-dev")
    transitioned = node_service.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    assert transitioned.status == NodeStatus.READY


def test_transition_node_blocked_requires_reason_code(setup):
    node_service, run = setup
    node = node_service.create_node(run.id, "Task", "backend", "backend-dev")
    with pytest.raises(ValueError, match="blockedReasonCode"):
        node_service.transition_node(node.id, NodeStatus.TODO, NodeStatus.BLOCKED, "missing reason")


def test_transition_node_invalid_transition(setup):
    node_service, run = setup
    node = node_service.create_node(run.id, "Task", "backend", "backend-dev")
    with pytest.raises(InvalidTransition):
        node_service.transition_node(node.id, NodeStatus.TODO, NodeStatus.DONE, "skip")


def test_transition_node_version_conflict(setup):
    node_service, run = setup
    node = node_service.create_node(run.id, "Task", "backend", "backend-dev")
    node_service.transition_node(node.id, NodeStatus.TODO, NodeStatus.READY, "ready")
    with pytest.raises(InvalidTransition, match="Expected run version"):
        node_service.transition_node(
            node.id,
            NodeStatus.READY,
            NodeStatus.RUNNING,
            "dispatch",
            expected_run_version=0,
        )
