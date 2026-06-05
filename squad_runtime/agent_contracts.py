from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict


class Evidence(TypedDict):
    type: str
    content: str


class ArtifactRef(TypedDict):
    name: str
    path: str


class Risk(TypedDict):
    level: Literal["low", "medium", "high"]
    description: str


class NextAction(TypedDict):
    action: str
    reason: str


@dataclass(frozen=True)
class AgentResult:
    taskNodeId: str
    agentId: str
    status: Literal["pass", "fail", "blocked"]
    summary: str
    evidence: list[Evidence]
    artifacts: list[ArtifactRef]
    risks: list[Risk]
    nextActions: list[NextAction]
    confidence: float
    workedAgainstCheckpoint: str
    agentContractVersion: str


@dataclass(frozen=True)
class AgentResultValidation:
    valid: bool
    errors: list[str]


def validate_agent_result(result: AgentResult, artifacts_dir: Path, expected_checkpoint: str | None) -> AgentResultValidation:
    errors: list[str] = []
    if result.status not in {"pass", "fail", "blocked"}:
        errors.append("invalid_status")
    if not result.taskNodeId:
        errors.append("missing_task_node_id")
    if not result.agentId:
        errors.append("missing_agent_id")
    if not result.summary:
        errors.append("missing_summary")
    if not 0.0 <= result.confidence <= 1.0:
        errors.append("confidence_out_of_range")
    if expected_checkpoint is not None and result.workedAgainstCheckpoint != expected_checkpoint:
        errors.append("checkpoint_mismatch")

    artifacts_root = artifacts_dir.resolve()
    for artifact in result.artifacts:
        artifact_path = (artifacts_root / artifact["path"]).resolve() if not Path(artifact["path"]).is_absolute() else Path(artifact["path"]).resolve()
        try:
            artifact_path.relative_to(artifacts_root)
        except ValueError:
            errors.append("artifact_path_invalid")

    return AgentResultValidation(valid=not errors, errors=sorted(set(errors)))
