from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def read_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_phase0_baseline_documents_exist_with_required_markers() -> None:
    expected_markers = {
        "BASELINE.md": ["c5db505", "acceptance baseline", "not a global threshold"],
        "docs/acceptance/baseline-evidence.md": [
            "run-5e18712d0c6e",
            "run-85631d7da7da",
            "provider=claude_cli",
            "synthetic=false",
            "gates=PASS",
        ],
        "docs/runtime/event-types.md": ["schemaVersion", "critical events", "high-frequency events"],
        "docs/runtime/agent-result-schema.md": ["AgentResult", "schemaVersion", "provider metadata"],
        "docs/runtime/runtime-facts.md": ["runtime facts", "artifacts", "verificationResults"],
        "docs/runtime/fact-coverage-matrix.md": ["Fact", "Gate", "Source"],
        "docs/runtime/failure-classification.md": ["failureClass", "SECURITY_VIOLATION", "EVIDENCE_MISSING"],
        "docs/runtime/frozen-resolved-profile.md": ["resolvedProfileHash", "sourceProfiles", "frozen"],
        "docs/runtime/event-hash-chain.md": ["eventHash", "previousEventHash", "finalEventHash"],
        "docs/runtime/profile-source-audit.md": ["commitHash", "contentHash", "sourceProfiles"],
        "docs/runtime/canonical-event-payload.md": ["canonical JSON", "schemaVersion", "payloadHash"],
        "docs/runtime/provider-prompt-hash.md": ["promptHash", "provider", "dispatch"],
        "docs/runtime/failure-severity-strategy.md": ["blocking", "warning", "Gate"],
        "docs/runtime/canonicalization-specification.md": ["NFC", "LF", "path separator"],
        "docs/runtime/chain-builder-versioning.md": ["chainBuilderVersion", "chainGraphHash", "version"],
        "schemas/README.md": ["Schema Registry", "schemaVersion", "migration"],
    }
    for relative_path, markers in expected_markers.items():
        text = read_text(relative_path)
        for marker in markers:
            assert marker in text, f"{relative_path} missing marker {marker!r}"


def test_phase0_golden_fixtures_capture_observations_not_thresholds() -> None:
    for relative_path, expected_run_id in [
        ("tests/fixtures/acceptance/dev-run-golden.json", "run-85631d7da7da"),
        ("tests/fixtures/acceptance/native-scene-f-golden.json", "run-5e18712d0c6e"),
    ]:
        fixture = json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))
        assert fixture["fixtureKind"] == "baseline_observation"
        assert fixture["thresholdPolicy"] == "observation_not_global_threshold"
        assert fixture["run"]["id"] == expected_run_id
        assert fixture["run"]["schemaVersion"] == "v1"
        assert fixture["provider"]["providerUsed"] == "claude_cli"
        assert fixture["provider"]["providerType"] == "real_llm"
        assert fixture["provider"]["syntheticDependency"] is False
        assert fixture["provider"]["providerFallback"] is False
        assert fixture["observedCounts"]["agentResults"] == 10
        assert fixture["observedCounts"]["nodes"] == 10
        assert set(fixture["gateStatus"].values()) == {"pass"}
