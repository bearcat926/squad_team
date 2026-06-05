# Squad Runtime Baseline

Captured: 2026-06-05

## Test Count

48 tests, all passing.

## Coverage

91% (1372 statements, 120 missed).

| Module | Coverage |
|--------|----------|
| __init__.py | 100% |
| acceptance.py | 92% |
| adapter.py | 97% |
| agent_contracts.py | 89% |
| agent_registry.py | 96% |
| api.py | 86% |
| checkpoints.py | 100% |
| cli.py | 87% |
| context.py | 97% |
| decisions.py | 83% |
| event_store.py | 96% |
| gate_engine.py | 95% |
| lead_decision.py | 100% |
| mock_agents.py | 83% |
| models.py | 100% |
| providers.py | 91% |
| runtime.py | 92% |
| scheduler.py | 91% |
| security.py | 78% |
| state.py | 100% |

## CLI Commands

`init`, `run`, `status`, `send`, `dispatch`, `eval-gates`, `start`, `open`,
`log-event`, `log-artifact`, `export-log`, `acceptance-report`, `archive`,
`agents list`, `agents doctor`, `token rotate`, `token show`.

## Runtime Public API

| Method | Returns |
|--------|---------|
| `create_run(goal, ...)` | SquadRun |
| `get_run(run_id)` | SquadRun |
| `list_runs()` | list[SquadRun] |
| `create_node(run_id, title, type, owner, ...)` | TaskNode |
| `get_node(node_id)` | TaskNode |
| `list_nodes(run_id)` | list[TaskNode] |
| `transition_node(node_id, from, to, reason, ...)` | TaskNode |
| `apply_agent_result(result)` | str |
| `persist_agent_result(result, ...)` | str |
| `list_agent_results(run_id)` | list[dict] |
| `list_evidence_items(run_id)` | list[dict] |
| `list_artifacts(run_id)` | list[dict] |
| `record_directive(run_id, message, ...)` | str |
| `upsert_gate_state(run_id, gate_name, status, reason, ...)` | None |
| `list_gate_states(run_id)` | list[dict] |
| `archive_run(run_id)` | Path |
| `record_event(run_id, event_type, payload)` | dict |
| `record_artifact(run_id, name, path, type)` | dict |
| `export_run_log(run_id, output_path, ...)` | Path |
| `create_review_finding(...)` | str |
| `supersede_review_finding(...)` | str |
| `list_review_findings(run_id)` | list[dict] |
| `list_review_finding_history(finding_id)` | list[dict] |
| `recover_running_dispatches()` | list[TaskNode] |
| `close()` | None |

## Provider Types

| Provider | Type | Notes |
|----------|------|-------|
| FakeCliProvider | deterministic | In-process mock |
| LocalCliProvider | real_llm | Subprocess CLI dispatch |

## API Routes

| Method | Path | Auth |
|--------|------|------|
| GET | /api/health | Public |
| GET | / | Public |
| GET | /static/* | Public |
| POST | /api/runs | Token |
| GET | /api/runs | No auth (gap) |
| GET | /api/runs/{run_id} | No auth (gap) |
| GET | /api/runs/{run_id}/nodes | No auth (gap) |
| GET | /api/runs/{run_id}/events | No auth (gap) |
| POST | /api/runs/{run_id}/directives | Token |
| GET | /api/runs/{run_id}/gates | No auth (gap) |
| POST | /api/runs/{run_id}/gates/evaluate | Token |
| POST | /api/runs/{run_id}/archive | Token |
