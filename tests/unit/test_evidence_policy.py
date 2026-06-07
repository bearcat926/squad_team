from __future__ import annotations

from squad_runtime.evidence_policy import EvidencePolicy, EvidenceScenarioType
from squad_runtime.profile_registry import ResolvedProfileLoader


def full_dev_facts() -> dict[str, object]:
    return {
        "agentResults": [
            {
                "agentId": "squad-lead",
                "providerUsed": "claude_cli",
                "providerType": "real_llm",
                "providerIdentityVerified": True,
                "providerFallbackTriggered": False,
                "synthetic": False,
            }
        ],
        "artifacts": [{"type": "mvp", "path": "mvp/index.html", "exists": True}],
        "verificationResults": [{"kind": "ui_smoke", "status": "pass"}],
        "coverageLanes": [{"lane": "Security Coverage Lane", "status": "pass"}],
        "skillUsage": [{"agentId": "squad-lead", "skill": "using-superpowers"}],
        "reviewFindings": [],
        "reviewArtifacts": [{"type": "review_fact", "contentHash": "sha256:review"}],
        "eventHashChain": {"status": "present", "finalEventHash": "sha256:event"},
    }


def test_full_dev_requires_profile_evidence_not_global_counts() -> None:
    profile = ResolvedProfileLoader.default().freeze(EvidenceScenarioType.FULL_DEV)
    facts = full_dev_facts()
    facts["artifacts"] = []

    result = EvidencePolicy(profile).evaluate(facts)

    assert result.status == "fail"
    assert result.schema_version == "evidence-gate/v1"
    assert result.missing[0].failure_class == "EVIDENCE_MISSING"
    assert result.missing[0].key == "artifact:mvp"
    assert result.resolved_profile_hash == profile.resolved_profile_hash


def test_smoke_profile_allows_missing_artifacts_with_warning() -> None:
    profile = ResolvedProfileLoader.default().freeze(EvidenceScenarioType.SMOKE)
    facts = full_dev_facts()
    facts["artifacts"] = []
    facts["verificationResults"] = []
    facts["coverageLanes"] = []
    facts["skillUsage"] = []

    result = EvidencePolicy(profile).evaluate(facts)

    assert result.status == "pass"
    assert result.warnings
    assert {warning.key for warning in result.warnings} >= {"artifact:any", "verification:any"}


def test_provider_and_tamper_failures_are_blocking() -> None:
    profile = ResolvedProfileLoader.default().freeze(EvidenceScenarioType.RELEASE)
    facts = full_dev_facts()
    facts["agentResults"] = [
        {
            "agentId": "test-engineer",
            "providerUsed": "fake_cli",
            "providerType": "deterministic",
            "providerIdentityVerified": False,
            "providerFallbackTriggered": False,
            "synthetic": True,
        }
    ]
    facts["artifacts"] = [{"type": "mvp", "path": "mvp/index.html", "exists": False}]
    facts["eventHashChain"] = {"status": "broken"}

    result = EvidencePolicy(profile).evaluate(facts)

    assert result.status == "fail"
    failure_classes = {item.failure_class for item in [*result.invalid, *result.tampered]}
    assert "PROVIDER_FAILURE" in failure_classes
    assert "EVIDENCE_TAMPERED" in failure_classes


def test_frozen_profile_is_immutable_after_source_profile_changes() -> None:
    loader = ResolvedProfileLoader.default()
    frozen = loader.freeze(EvidenceScenarioType.FULL_DEV)
    mutated = loader.with_overrides({"requiredArtifacts": ["unexpected"]})

    assert frozen.resolved_profile_hash != mutated.freeze(EvidenceScenarioType.FULL_DEV).resolved_profile_hash
    assert "mvp" in frozen.requirements.required_artifact_types
