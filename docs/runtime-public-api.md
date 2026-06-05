# Runtime Public API

Frozen: 2026-06-05

This document enumerates the public API of the `Runtime` class. All
contract tests in `tests/contract/test_runtime_public_api.py` verify
that these methods exist with the documented signatures.

## Constructor

| Method | Signature | Returns |
|--------|-----------|---------|
| `__init__` | `(squad_dir: Path)` | None |
| `create` | `(squad_dir: Path) -> Runtime` | Runtime (classmethod) |

## Run Management

| Method | Signature | Returns |
|--------|-----------|---------|
| `create_run` | `(goal, rule_version="v1", schema_version="v1", agent_contract_version="v1")` | `SquadRun` |
| `get_run` | `(run_id: str)` | `SquadRun` |
| `list_runs` | `()` | `list[SquadRun]` |

## Node Management

| Method | Signature | Returns |
|--------|-----------|---------|
| `create_node` | `(run_id, title, node_type, owner_agent_id, checkpoint_id="ckp-1")` | `TaskNode` |
| `get_node` | `(node_id: str)` | `TaskNode` |
| `list_nodes` | `(run_id: str)` | `list[TaskNode]` |
| `transition_node` | `(node_id, from_status, to_status, reason, blocked_reason_code=None, metadata=None, expected_run_version=None)` | `TaskNode` |

## Agent Results

| Method | Signature | Returns |
|--------|-----------|---------|
| `apply_agent_result` | `(result: AgentResult)` | `str` |
| `persist_agent_result` | `(result, provider_used, provider_type="deterministic", provider_identity_verified=False, provider_fallback_triggered=False, fallback_reason=None, synthetic=False)` | `str` |
| `list_agent_results` | `(run_id: str)` | `list[dict]` |
| `list_evidence_items` | `(run_id: str)` | `list[dict]` |
| `list_artifacts` | `(run_id: str)` | `list[dict]` |

## Directives

| Method | Signature | Returns |
|--------|-----------|---------|
| `record_directive` | `(run_id, message, source="user")` | `str` |

## Gates

| Method | Signature | Returns |
|--------|-----------|---------|
| `upsert_gate_state` | `(run_id, gate_name, status, reason, blocked_reason_code=None)` | `None` |
| `list_gate_states` | `(run_id: str)` | `list[dict]` |

## Review Findings

| Method | Signature | Returns |
|--------|-----------|---------|
| `create_review_finding` | `(run_id, task_node_id, author_agent_id, severity, description)` | `str` |
| `supersede_review_finding` | `(finding_id, author_agent_id, severity, description)` | `str` |
| `list_review_findings` | `(run_id: str)` | `list[dict]` |
| `list_review_finding_history` | `(finding_id: str)` | `list[dict]` |

## Events and Artifacts

| Method | Signature | Returns |
|--------|-----------|---------|
| `record_event` | `(run_id, event_type, payload)` | `dict` |
| `record_artifact` | `(run_id, name, path, artifact_type)` | `dict` |

## Archiving and Export

| Method | Signature | Returns |
|--------|-----------|---------|
| `archive_run` | `(run_id: str)` | `Path` |
| `export_run_log` | `(run_id, output_path, include_export_event=False)` | `Path` |

## Recovery

| Method | Signature | Returns |
|--------|-----------|---------|
| `recover_running_dispatches` | `()` | `list[TaskNode]` |

## Lifecycle

| Method | Signature | Returns |
|--------|-----------|---------|
| `close` | `()` | `None` |
