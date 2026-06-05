"""Pydantic v2 DTOs for the Squad Runtime HTTP API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ── Request DTOs ────────────────────────────────────────────────────────


class CreateRunRequest(BaseModel):
    """Create a new squad run."""

    goal: str = Field(..., min_length=1, description="High-level goal for the run")


class DirectiveRequest(BaseModel):
    """Submit a lead directive to a run."""

    message: str = Field(..., min_length=1, description="Directive message text")


# ── Response DTOs ───────────────────────────────────────────────────────


class RunResponse(BaseModel):
    """Representation of a squad run."""

    id: str
    goal: str
    status: str
    version: int
    ruleVersion: str
    schemaVersion: str
    agentContractVersion: str


class NodeResponse(BaseModel):
    """Representation of a task node within a run."""

    id: str
    runId: str
    title: str
    type: str
    ownerAgentId: str
    status: str
    blockedReasonCode: str | None = None
    checkpointId: str
    replacedByNodeId: str | None = None


class EventResponse(BaseModel):
    """Representation of an event in the event store."""

    id: str
    runId: str
    sequenceNumber: int
    type: str
    payload: dict[str, Any]
    critical: bool
    createdAt: str


class GateResponse(BaseModel):
    """Representation of a gate decision."""

    gateName: str
    status: str
    reason: str
    blocking: bool = True
    blockedReasonCode: str | None = None
    details: dict[str, Any] | None = None


class DirectiveDecisionResponse(BaseModel):
    """Response after applying a directive."""

    directiveId: str
    bypassAttempt: bool
    actions: list[str]


class DirectiveEnvelope(BaseModel):
    """Envelope wrapping a directive decision."""

    decision: DirectiveDecisionResponse


class RunListResponse(BaseModel):
    """List of runs."""

    runs: list[RunResponse]


class NodeListResponse(BaseModel):
    """List of nodes."""

    nodes: list[NodeResponse]


class EventListResponse(BaseModel):
    """Paginated list of events."""

    events: list[EventResponse]
    nextCursor: int | None = None


class GateListResponse(BaseModel):
    """List of gate states."""

    gates: list[dict[str, Any]]


class GateEvaluationResponse(BaseModel):
    """Result of evaluating all gates."""

    gates: dict[str, Any]


class ArchiveResponse(BaseModel):
    """Response after archiving a run."""

    archivePath: str


class HealthResponse(BaseModel):
    """Health check response."""

    status: str


# ── Error DTOs ──────────────────────────────────────────────────────────


class ErrorDetail(BaseModel):
    """Structured error detail."""

    code: str
    message: str
    traceId: str


class ErrorResponse(BaseModel):
    """Unified error envelope."""

    error: ErrorDetail
