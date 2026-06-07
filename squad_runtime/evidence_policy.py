from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .profile_registry import EvidenceScenarioType, FrozenResolvedProfile

__all__ = ["EvidenceGateResult", "EvidenceIssue", "EvidencePolicy", "EvidenceScenarioType"]


@dataclass(frozen=True)
class EvidenceIssue:
    key: str
    failure_class: str
    message: str
    severity: str = "blocking"

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "failureClass": self.failure_class,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class EvidenceGateResult:
    status: str
    schema_version: str
    resolved_profile_hash: str
    missing: tuple[EvidenceIssue, ...] = ()
    invalid: tuple[EvidenceIssue, ...] = ()
    tampered: tuple[EvidenceIssue, ...] = ()
    warnings: tuple[EvidenceIssue, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "schemaVersion": self.schema_version,
            "resolvedProfileHash": self.resolved_profile_hash,
            "missing": [issue.to_dict() for issue in self.missing],
            "invalid": [issue.to_dict() for issue in self.invalid],
            "tampered": [issue.to_dict() for issue in self.tampered],
            "warnings": [issue.to_dict() for issue in self.warnings],
        }


class EvidencePolicy:
    """Evaluates runtime facts against a frozen resolved evidence profile."""

    def __init__(self, profile: FrozenResolvedProfile):
        self.profile = profile

    def evaluate(self, facts: dict[str, Any]) -> EvidenceGateResult:
        missing: list[EvidenceIssue] = []
        invalid: list[EvidenceIssue] = []
        tampered: list[EvidenceIssue] = []
        warnings: list[EvidenceIssue] = []

        requirements = self.profile.requirements
        artifacts = list(facts.get("artifacts", []))
        verification_results = list(facts.get("verificationResults", []))
        coverage_lanes = list(facts.get("coverageLanes", []))
        skill_usage = list(facts.get("skillUsage", []))

        if requirements.require_real_provider:
            invalid.extend(self._provider_issues(list(facts.get("agentResults", []))))

        for artifact_type in requirements.required_artifact_types:
            matched = [artifact for artifact in artifacts if artifact.get("type") == artifact_type]
            if not matched:
                missing.append(EvidenceIssue(f"artifact:{artifact_type}", "EVIDENCE_MISSING", f"Missing artifact type {artifact_type}"))
            for artifact in matched:
                if artifact.get("exists") is False:
                    missing.append(EvidenceIssue(f"artifact:{artifact_type}:path", "EVIDENCE_MISSING", f"Artifact path missing: {artifact.get('path')}"))
                if artifact.get("hashMatches") is False:
                    tampered.append(EvidenceIssue(f"artifact:{artifact_type}:hash", "EVIDENCE_TAMPERED", f"Artifact hash mismatch: {artifact.get('path')}"))

        for artifact_type in requirements.warning_artifact_types:
            if artifact_type == "any" and not artifacts:
                warnings.append(EvidenceIssue("artifact:any", "EVIDENCE_MISSING", "Smoke profile has no artifacts", "warning"))

        for verification_kind in requirements.required_verification_kinds:
            if not any(item.get("kind") == verification_kind and item.get("status") == "pass" for item in verification_results):
                missing.append(
                    EvidenceIssue(
                        f"verification:{verification_kind}",
                        "EVIDENCE_MISSING",
                        f"Missing verification kind {verification_kind}",
                    )
                )

        for verification_kind in requirements.warning_verification_kinds:
            if verification_kind == "any" and not verification_results:
                warnings.append(EvidenceIssue("verification:any", "EVIDENCE_MISSING", "Smoke profile has no verification results", "warning"))

        for lane in requirements.required_coverage_lanes:
            if not any(item.get("lane") == lane and item.get("status") == "pass" for item in coverage_lanes):
                missing.append(EvidenceIssue(f"coverageLane:{lane}", "EVIDENCE_MISSING", f"Missing coverage lane {lane}"))

        for skill in requirements.required_skill_usages:
            if not any(item.get("skill") == skill for item in skill_usage):
                missing.append(EvidenceIssue(f"skill:{skill}", "EVIDENCE_MISSING", f"Missing skill usage {skill}"))

        if requirements.require_review_artifact and not self._has_review_artifact(facts):
            missing.append(EvidenceIssue("reviewArtifact", "EVIDENCE_MISSING", "Missing Review Artifact or Review Fact"))

        if requirements.require_event_hash_chain:
            chain = facts.get("eventHashChain") or {}
            if chain.get("status") != "present" or not chain.get("finalEventHash"):
                tampered.append(EvidenceIssue("eventHashChain", "EVIDENCE_TAMPERED", "Event hash chain missing or broken"))

        status = "fail" if missing or invalid or tampered else "pass"
        return EvidenceGateResult(
            status=status,
            schema_version="evidence-gate/v1",
            resolved_profile_hash=self.profile.resolved_profile_hash,
            missing=tuple(missing),
            invalid=tuple(invalid),
            tampered=tuple(tampered),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _provider_issues(results: list[dict[str, Any]]) -> list[EvidenceIssue]:
        issues: list[EvidenceIssue] = []
        for result in results:
            agent_id = result.get("agentId", "unknown")
            if result.get("providerUsed") != "claude_cli":
                issues.append(EvidenceIssue(f"provider:{agent_id}", "PROVIDER_FAILURE", f"{agent_id} did not use claude_cli"))
            if result.get("providerType") != "real_llm":
                issues.append(EvidenceIssue(f"providerType:{agent_id}", "PROVIDER_FAILURE", f"{agent_id} was not real_llm"))
            if not result.get("providerIdentityVerified"):
                issues.append(EvidenceIssue(f"providerIdentity:{agent_id}", "PROVIDER_FAILURE", f"{agent_id} provider identity not verified"))
            if result.get("providerFallbackTriggered"):
                issues.append(EvidenceIssue(f"providerFallback:{agent_id}", "PROVIDER_FAILURE", f"{agent_id} used provider fallback"))
            if result.get("synthetic"):
                issues.append(EvidenceIssue(f"synthetic:{agent_id}", "PROVIDER_FAILURE", f"{agent_id} used synthetic result"))
        return issues

    @staticmethod
    def _has_review_artifact(facts: dict[str, Any]) -> bool:
        if facts.get("reviewArtifacts"):
            return True
        return any(artifact.get("type") in {"review", "review_fact", "review-artifact"} for artifact in facts.get("artifacts", []))
