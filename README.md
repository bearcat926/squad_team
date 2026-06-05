# Squad Runtime

Local single-user runtime for auditable Squad-style agent execution.

The MVP proves a replacement runtime shape for multi-agent project work:

- Runtime is the only writer of node, gate, and database state.
- LLM agents run through `AgentRuntimeAdapter` and return validated `AgentResult` objects.
- Agent sessions are isolated by dispatch, prompt, memory, and artifact directory.
- Gates read SQLite fact tables, not free-form event payloads.
- Full-team acceptance uses 10 active runtime agents with `claude_cli` as the real LLM provider.

## Quick Start

```powershell
python -m pip install -e .
python -m squad_runtime init
python -m squad_runtime run "Build and validate a local MVP"
python -m squad_runtime status
```

## Real LLM Acceptance

The acceptance runner executes serial real-LLM dispatches and writes:

- `FULL_DATA_LOG.md`
- `ANALYSIS_REPORT.zh-CN.md`
- `acceptance-report.md`
- `.squad/runs/<run_id>/archive.json`

```powershell
python scripts\acceptance\run_real_llm_acceptance.py `
  --scenario full-team `
  --provider claude_cli `
  --acceptance-root E:\Project\squad-runtime-index-mirror `
  --coverage-percent 91 `
  --codebase-memory-status indexed `
  --codebase-memory-project E-Project-squad-runtime-index-mirror `
  --codebase-memory-nodes 3726 `
  --codebase-memory-edges 5337 `
  --architecture-status ok
```

Latest verified run: `run-8493cf152341`.

## Verification

```powershell
python -m pytest tests -q
python -m pytest tests -q --cov=squad_runtime --cov-report=term-missing
```

Current verification:

- Tests: `48 passed`
- Coverage: `91%`
- Full-team real LLM acceptance: `PASS`
- Codebase memory graph: `indexed`, `3726 nodes`, `5337 edges`

## Safety Notes

Do not commit local runtime secrets or mutable state:

- `.squad/token`
- `.squad/squad.db`
- `.squad/events.ndjson`
- `.squad/runs/`

Root-level final reports are safe to publish as release evidence.
