"""Tests for API authentication enforcement."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from squad_runtime.api import create_app
from squad_runtime.security import initialize_project


def test_no_token_returns_401_on_runs_list(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    initialize_project(squad_dir)
    client = TestClient(create_app(squad_dir))

    resp = client.get("/api/runs")

    assert resp.status_code == 401


def test_wrong_token_returns_401(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    initialize_project(squad_dir)
    client = TestClient(create_app(squad_dir))

    resp = client.get("/api/runs", headers={"X-Squad-Token": "wrong-token"})

    assert resp.status_code == 401


def test_correct_token_returns_200(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    token = initialize_project(squad_dir).token
    client = TestClient(create_app(squad_dir))

    resp = client.get("/api/runs", headers={"X-Squad-Token": token})

    assert resp.status_code == 200


def test_health_endpoint_public(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    initialize_project(squad_dir)
    client = TestClient(create_app(squad_dir))

    resp = client.get("/api/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_root_endpoint_public(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    initialize_project(squad_dir)
    client = TestClient(create_app(squad_dir))

    resp = client.get("/")

    assert resp.status_code == 200


def test_run_detail_requires_token(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    token = initialize_project(squad_dir).token
    client = TestClient(create_app(squad_dir))

    # Create a run with valid token
    created = client.post("/api/runs", json={"goal": "test"}, headers={"X-Squad-Token": token})
    run_id = created.json()["id"]

    # GET without token should fail
    assert client.get(f"/api/runs/{run_id}").status_code == 401

    # GET with token should pass
    assert client.get(f"/api/runs/{run_id}", headers={"X-Squad-Token": token}).status_code == 200


def test_nodes_endpoint_requires_token(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    token = initialize_project(squad_dir).token
    client = TestClient(create_app(squad_dir))

    created = client.post("/api/runs", json={"goal": "test"}, headers={"X-Squad-Token": token})
    run_id = created.json()["id"]

    assert client.get(f"/api/runs/{run_id}/nodes").status_code == 401
    assert client.get(f"/api/runs/{run_id}/nodes", headers={"X-Squad-Token": token}).status_code == 200


def test_events_endpoint_requires_token(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    token = initialize_project(squad_dir).token
    client = TestClient(create_app(squad_dir))

    created = client.post("/api/runs", json={"goal": "test"}, headers={"X-Squad-Token": token})
    run_id = created.json()["id"]

    assert client.get(f"/api/runs/{run_id}/events").status_code == 401
    assert client.get(f"/api/runs/{run_id}/events", headers={"X-Squad-Token": token}).status_code == 200


def test_gates_endpoint_requires_token(tmp_path: Path):
    squad_dir = tmp_path / ".squad"
    token = initialize_project(squad_dir).token
    client = TestClient(create_app(squad_dir))

    created = client.post("/api/runs", json={"goal": "test"}, headers={"X-Squad-Token": token})
    run_id = created.json()["id"]

    assert client.get(f"/api/runs/{run_id}/gates").status_code == 401
    assert client.get(f"/api/runs/{run_id}/gates", headers={"X-Squad-Token": token}).status_code == 200
