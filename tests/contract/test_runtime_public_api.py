"""Contract tests verifying the Runtime public API surface.

These tests ensure backward compatibility: every public method listed in
docs/runtime-public-api.md must exist with the expected signature.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from squad_runtime.runtime import Runtime


def _public_methods() -> dict[str, inspect.Signature]:
    results: dict[str, inspect.Signature] = {}
    for name, method in inspect.getmembers(Runtime):
        if name.startswith("_"):
            continue
        if inspect.isfunction(method) or inspect.ismethod(method):
            results[name] = inspect.signature(method)
    return results


def test_public_api_contains_all_expected_methods():
    methods = _public_methods()
    expected = {
        "create",
        "create_run",
        "get_run",
        "list_runs",
        "create_node",
        "get_node",
        "list_nodes",
        "transition_node",
        "apply_agent_result",
        "persist_agent_result",
        "list_agent_results",
        "list_evidence_items",
        "list_artifacts",
        "record_directive",
        "upsert_gate_state",
        "list_gate_states",
        "archive_run",
        "record_event",
        "record_artifact",
        "export_run_log",
        "create_review_finding",
        "supersede_review_finding",
        "list_review_findings",
        "list_review_finding_history",
        "recover_running_dispatches",
        "close",
    }
    missing = expected - set(methods.keys())
    assert not missing, f"Missing public methods: {missing}"


def test_create_run_signature():
    sig = inspect.signature(Runtime.create_run)
    params = list(sig.parameters.keys())
    assert "self" in params
    assert "goal" in params
    assert "rule_version" in params
    assert "schema_version" in params
    assert "agent_contract_version" in params


def test_create_node_signature():
    sig = inspect.signature(Runtime.create_node)
    params = list(sig.parameters.keys())
    assert "self" in params
    assert "run_id" in params
    assert "title" in params
    assert "node_type" in params
    assert "owner_agent_id" in params
    assert "checkpoint_id" in params


def test_transition_node_signature():
    sig = inspect.signature(Runtime.transition_node)
    params = list(sig.parameters.keys())
    assert "self" in params
    assert "node_id" in params
    assert "from_status" in params
    assert "to_status" in params
    assert "reason" in params
    assert "blocked_reason_code" in params
    assert "metadata" in params
    assert "expected_run_version" in params


def test_persist_agent_result_signature():
    sig = inspect.signature(Runtime.persist_agent_result)
    params = list(sig.parameters.keys())
    assert "self" in params
    assert "result" in params
    assert "provider_used" in params
    assert "provider_type" in params
    assert "provider_identity_verified" in params
    assert "provider_fallback_triggered" in params
    assert "fallback_reason" in params
    assert "synthetic" in params


def test_archive_run_returns_path():
    runtime = Runtime(Path("does_not_exist_for_contract_test"))
    # Verify the method exists and is callable; full return type checked via integration tests
    assert callable(runtime.archive_run)


def test_close_is_callable():
    runtime = Runtime(Path("does_not_exist_for_contract_test"))
    assert callable(runtime.close)
