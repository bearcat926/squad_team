"""Tests for API Pydantic v2 DTOs defined in api_schemas.py."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from squad_runtime.api_schemas import (
    ArchiveResponse,
    CreateRunRequest,
    DirectiveEnvelope,
    DirectiveRequest,
    ErrorDetail,
    ErrorResponse,
    EventListResponse,
    EventResponse,
    GateEvaluationResponse,
    GateListResponse,
    GateResponse,
    HealthResponse,
    NodeListResponse,
    NodeResponse,
    RunListResponse,
    RunResponse,
)

# -- Request DTOs --


class TestCreateRunRequest:
    def test_valid(self):
        req = CreateRunRequest(goal="ship MVP")
        assert req.goal == "ship MVP"

    def test_empty_goal_rejected(self):
        with pytest.raises(ValidationError):
            CreateRunRequest(goal="")

    def test_missing_goal_rejected(self):
        with pytest.raises(ValidationError):
            CreateRunRequest()  # type: ignore[call-arg]


class TestDirectiveRequest:
    def test_valid(self):
        req = DirectiveRequest(message="proceed to testing")
        assert req.message == "proceed to testing"

    def test_empty_message_rejected(self):
        with pytest.raises(ValidationError):
            DirectiveRequest(message="")

    def test_missing_message_rejected(self):
        with pytest.raises(ValidationError):
            DirectiveRequest()  # type: ignore[call-arg]


# ── Response DTOs ───────────────────────────────────────────────────────


class TestRunResponse:
    def test_from_dict(self):
        data = {
            "id": "run-1",
            "goal": "test",
            "status": "active",
            "version": 1,
            "ruleVersion": "v1",
            "schemaVersion": "v1",
            "agentContractVersion": "v1",
        }
        resp = RunResponse(**data)
        assert resp.id == "run-1"
        assert resp.version == 1

    def test_roundtrip(self):
        data = {
            "id": "run-2",
            "goal": "build",
            "status": "archived",
            "version": 3,
            "ruleVersion": "v1",
            "schemaVersion": "v1",
            "agentContractVersion": "v1",
        }
        resp = RunResponse(**data)
        dumped = resp.model_dump()
        assert dumped["id"] == "run-2"
        assert dumped["version"] == 3


class TestNodeResponse:
    def test_all_fields(self):
        data = {
            "id": "node-1",
            "runId": "run-1",
            "title": "Backend impl",
            "type": "backend",
            "ownerAgentId": "backend-architect",
            "status": "running",
            "blockedReasonCode": None,
            "checkpointId": "ckp-1",
            "replacedByNodeId": None,
        }
        resp = NodeResponse(**data)
        assert resp.status == "running"
        assert resp.blockedReasonCode is None

    def test_with_blocked_reason(self):
        data = {
            "id": "node-2",
            "runId": "run-1",
            "title": "Test task",
            "type": "test",
            "ownerAgentId": "test-engineer",
            "status": "blocked",
            "blockedReasonCode": "missing_test_pass",
            "checkpointId": "ckp-1",
        }
        resp = NodeResponse(**data)
        assert resp.blockedReasonCode == "missing_test_pass"


class TestEventResponse:
    def test_valid(self):
        data = {
            "id": "evt-1",
            "runId": "run-1",
            "sequenceNumber": 1,
            "type": "run_created",
            "payload": {"goal": "test"},
            "critical": True,
            "createdAt": "2026-01-01T00:00:00Z",
        }
        resp = EventResponse(**data)
        assert resp.sequenceNumber == 1
        assert resp.payload["goal"] == "test"


class TestGateResponse:
    def test_valid(self):
        data = {
            "gateName": "test_gate",
            "status": "pass",
            "reason": "all tests passed",
            "blocking": True,
            "blockedReasonCode": None,
            "details": None,
        }
        resp = GateResponse(**data)
        assert resp.status == "pass"

    def test_with_details(self):
        data = {
            "gateName": "release_gate",
            "status": "blocked",
            "reason": "missing review",
            "blocking": True,
            "blockedReasonCode": "missing_review_pass",
            "details": {"missing": ["code_review_gate"]},
        }
        resp = GateResponse(**data)
        assert resp.details is not None
        assert "missing" in resp.details


class TestDirectiveEnvelope:
    def test_valid(self):
        data = {
            "decision": {
                "directiveId": "dir-1",
                "bypassAttempt": False,
                "actions": ["directive_recorded"],
            }
        }
        resp = DirectiveEnvelope(**data)
        assert resp.decision.directiveId == "dir-1"
        assert resp.decision.actions == ["directive_recorded"]


# ── List / Envelope DTOs ────────────────────────────────────────────────


class TestListResponses:
    def test_run_list_response(self):
        resp = RunListResponse(runs=[])
        assert resp.runs == []

    def test_node_list_response(self):
        resp = NodeListResponse(nodes=[])
        assert resp.nodes == []

    def test_event_list_response(self):
        resp = EventListResponse(events=[], nextCursor=None)
        assert resp.events == []
        assert resp.nextCursor is None

    def test_gate_list_response(self):
        resp = GateListResponse(gates=[])
        assert resp.gates == []

    def test_gate_evaluation_response(self):
        resp = GateEvaluationResponse(gates={"test_gate": {"status": "pass"}})
        assert resp.gates["test_gate"]["status"] == "pass"

    def test_archive_response(self):
        resp = ArchiveResponse(archivePath="/tmp/archive.tar.gz")
        assert resp.archivePath == "/tmp/archive.tar.gz"

    def test_health_response(self):
        resp = HealthResponse(status="ok")
        assert resp.status == "ok"


# ── Error DTOs ──────────────────────────────────────────────────────────


class TestErrorDTOs:
    def test_error_detail(self):
        detail = ErrorDetail(code="not_found", message="Run not found", traceId="abc-123")
        assert detail.code == "not_found"

    def test_error_response_envelope(self):
        resp = ErrorResponse(error=ErrorDetail(code="bad_request", message="Invalid input", traceId="xyz"))
        dumped = resp.model_dump()
        assert dumped["error"]["code"] == "bad_request"
        assert dumped["error"]["traceId"] == "xyz"

    def test_error_response_roundtrip(self):
        resp = ErrorResponse(error=ErrorDetail(code="forbidden", message="Access denied", traceId="trace-1"))
        json_str = resp.model_dump_json()
        assert "forbidden" in json_str
        assert "trace-1" in json_str
