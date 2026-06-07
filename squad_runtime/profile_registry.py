from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class EvidenceScenarioType(StrEnum):
    SMOKE = "smoke"
    MVP = "mvp"
    FULL_DEV = "full_dev"
    RELEASE = "release"
    REAL_ACCEPTANCE = "real_acceptance"


@dataclass(frozen=True)
class EvidenceRequirements:
    required_artifact_types: tuple[str, ...] = ()
    warning_artifact_types: tuple[str, ...] = ()
    required_verification_kinds: tuple[str, ...] = ()
    warning_verification_kinds: tuple[str, ...] = ()
    required_coverage_lanes: tuple[str, ...] = ()
    required_skill_usages: tuple[str, ...] = ()
    require_review_artifact: bool = False
    require_event_hash_chain: bool = False
    require_real_provider: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "requiredArtifactTypes": list(self.required_artifact_types),
            "warningArtifactTypes": list(self.warning_artifact_types),
            "requiredVerificationKinds": list(self.required_verification_kinds),
            "warningVerificationKinds": list(self.warning_verification_kinds),
            "requiredCoverageLanes": list(self.required_coverage_lanes),
            "requiredSkillUsages": list(self.required_skill_usages),
            "requireReviewArtifact": self.require_review_artifact,
            "requireEventHashChain": self.require_event_hash_chain,
            "requireRealProvider": self.require_real_provider,
        }


@dataclass(frozen=True)
class FrozenResolvedProfile:
    schema_version: str
    scenario_type: EvidenceScenarioType
    requirements: EvidenceRequirements
    resolved_profile_hash: str
    source_profiles: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "scenarioType": self.scenario_type.value,
            "requirements": self.requirements.to_dict(),
            "resolvedProfileHash": self.resolved_profile_hash,
            "sourceProfiles": list(self.source_profiles),
        }


class ResolvedProfileLoader:
    """Builds frozen evidence profiles from built-in profile sources."""

    def __init__(self, overrides: dict[str, Any] | None = None):
        self._overrides = overrides or {}

    @classmethod
    def default(cls) -> ResolvedProfileLoader:
        return cls()

    def with_overrides(self, overrides: dict[str, Any]) -> ResolvedProfileLoader:
        return ResolvedProfileLoader({**self._overrides, **overrides})

    def freeze(self, scenario_type: EvidenceScenarioType | str) -> FrozenResolvedProfile:
        scenario = EvidenceScenarioType(scenario_type)
        requirements = self._requirements_for(scenario)
        requirements = self._apply_overrides(requirements)
        source_profile = self._source_profile(requirements, scenario)
        profile_payload = {
            "schemaVersion": "resolved-profile/v1",
            "scenarioType": scenario.value,
            "requirements": requirements.to_dict(),
            "sourceProfiles": [source_profile],
        }
        resolved_hash = hashlib.sha256(json.dumps(profile_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return FrozenResolvedProfile(
            schema_version="resolved-profile/v1",
            scenario_type=scenario,
            requirements=requirements,
            resolved_profile_hash=f"sha256:{resolved_hash}",
            source_profiles=(source_profile,),
        )

    def _requirements_for(self, scenario: EvidenceScenarioType) -> EvidenceRequirements:
        if scenario is EvidenceScenarioType.SMOKE:
            return EvidenceRequirements(
                warning_artifact_types=("any",),
                warning_verification_kinds=("any",),
                require_review_artifact=False,
                require_event_hash_chain=False,
            )
        if scenario is EvidenceScenarioType.MVP:
            return EvidenceRequirements(
                required_artifact_types=("mvp",),
                required_verification_kinds=("ui_smoke",),
                required_skill_usages=("using-superpowers",),
                require_review_artifact=True,
            )
        return EvidenceRequirements(
            required_artifact_types=("mvp",),
            required_verification_kinds=("ui_smoke",),
            required_coverage_lanes=("Security Coverage Lane",),
            required_skill_usages=("using-superpowers",),
            require_review_artifact=True,
            require_event_hash_chain=True,
        )

    def _apply_overrides(self, requirements: EvidenceRequirements) -> EvidenceRequirements:
        if not self._overrides:
            return requirements
        return EvidenceRequirements(
            required_artifact_types=tuple(self._overrides.get("requiredArtifacts", requirements.required_artifact_types)),
            warning_artifact_types=tuple(self._overrides.get("warningArtifacts", requirements.warning_artifact_types)),
            required_verification_kinds=tuple(self._overrides.get("requiredVerifications", requirements.required_verification_kinds)),
            warning_verification_kinds=tuple(self._overrides.get("warningVerifications", requirements.warning_verification_kinds)),
            required_coverage_lanes=tuple(self._overrides.get("requiredCoverageLanes", requirements.required_coverage_lanes)),
            required_skill_usages=tuple(self._overrides.get("requiredSkillUsages", requirements.required_skill_usages)),
            require_review_artifact=bool(self._overrides.get("requireReviewArtifact", requirements.require_review_artifact)),
            require_event_hash_chain=bool(self._overrides.get("requireEventHashChain", requirements.require_event_hash_chain)),
            require_real_provider=bool(self._overrides.get("requireRealProvider", requirements.require_real_provider)),
        )

    def _source_profile(self, requirements: EvidenceRequirements, scenario: EvidenceScenarioType) -> dict[str, str]:
        content = json.dumps(
            {"scenarioType": scenario.value, "requirements": requirements.to_dict()},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "path": "builtin://evidence-profile/default",
            "commitHash": "workspace",
            "contentHash": f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}",
            "schemaVersion": "source-profile/v1",
        }
