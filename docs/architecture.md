# Squad Runtime Architecture

## Overview

Squad Runtime is a local, single-user orchestration engine that coordinates
multi-agent software development workflows. It tracks task nodes through a
state machine, enforces quality gates, and dispatches work to LLM providers.

## Layered Architecture

```
CLI / API
    |
Runtime (Facade)
    |
Services ──────────────── Repositories
    |                         |
EventStore                Database (SQLite)
    |
NDJSON Audit Mirror
```

### Runtime (Facade)

`runtime.py` is a **backward-compatible facade** that wires together all
services and repositories. It owns no SQL and delegates every operation to the
appropriate service.

### Services

| Service | Responsibility |
|---------|----------------|
| `RunService` | CRUD for runs |
| `NodeService` | CRUD + state transitions for task nodes |
| `AgentResultService` | Persist and apply agent results |
| `GateService` | Gate state upsert and query |
| `ArchiveService` | Archive and export run logs |

Services never import `sqlite3` directly; all data access goes through
repositories.

### Repositories

| Repository | Table(s) |
|------------|----------|
| `RunRepository` | `squad_runs` |
| `NodeRepository` | `task_nodes` |
| `GateRepository` | `gate_states` |
| `ArtifactRepository` | `agent_results`, `evidence_items`, `artifacts`, `review_findings` |
| `EventRepository` | delegates to `EventStore` |

Each repository takes a `sqlite3.Connection` in its constructor.

### Infrastructure

- **Database** – creates the SQLite connection, sets WAL mode and busy_timeout.
- **Schema / Migrations** – lightweight migration system with a
  `schema_version` table. Migrations run in order; only upgrade is supported.

## Provider Execution Flow

```
LocalCliProvider
  ├── Workspace         (dispatch dir, context, prompt files)
  ├── PromptBuilder     (builds the prompt string)
  ├── ProcessRunner     (subprocess.run with timeout)
  └── ResultParser      (final-result.json > stdout JSON > CLI wrapper)
```

`FakeCliProvider` is the in-process deterministic mock used in tests.

## Event Store

Dual-write: every event is persisted to both **SQLite** (`squad_events` table)
and an **NDJSON audit file** (`events.ndjson`). On startup, if the two
diverge, the NDJSON is rebuilt from SQLite and a consistency warning is
recorded.

## Gate Engine

Four gates are evaluated in dependency order:

1. **test_gate** – requires passing test-engineer results
2. **code_review_gate** – requires passing code-reviewer results
3. **reality_checker_gate** – requires test_gate to pass first
4. **release_gate** – requires all three prerequisite gates to pass

## Node State Machine

```
TODO → READY → RUNNING → PASS → DONE
                  │         │
                  │         └→ STALE (terminal)
                  │
                  ├→ FAIL → READY (retry)
                  ├→ BLOCKED → READY (retry)
                  ├→ AGENT_UNAVAILABLE → READY (retry)
                  ├→ PROGRESS_TIMEOUT → READY (retry)
                  ├→ CANCELED → DONE
                  └→ STALE (terminal)
```

Terminal states: `PASS`, `FAIL`, `BLOCKED`, `AGENT_UNAVAILABLE`, `CANCELED`,
`STALE`, `DONE`.
