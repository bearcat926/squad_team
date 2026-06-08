# Mutation Testing

## What Is Mutation Testing?

Mutation testing introduces small changes (mutations) into source code -- for example, replacing `>` with `>=`, deleting a line, or swapping `+` for `-`. Each mutant is then run against the test suite. If a test fails, the mutant is **killed** (good). If all tests still pass, the mutant **survived** (the test suite missed it).

The mutation score is:

```
score = (killed + timeout) / (killed + survived + timeout) * 100
```

A higher score means the test suite is more effective at catching real bugs.

## Threshold Policy

| Metric | Threshold |
|--------|-----------|
| Mutation Score | >= 60% |

The threshold is enforced by `scripts/parse_mutation_score.py`. If the score falls below 60%, the CI step exits with code 1 and the build is marked as failed.

## Running Locally

```bash
# Install dev dependencies (includes mutmut>=2.4,<3)
pip install -e ".[dev]"

# Run mutation testing on core modules
mutmut run --paths-to-mutate \
  "squad_runtime/state.py" \
  "squad_runtime/gate_engine.py" \
  "squad_runtime/security/" \
  "squad_runtime/services/" \
  "squad_runtime/repositories/" \
  "squad_runtime/providers/" \
  "squad_runtime/event_store.py"

# View results
mutmut results

# Generate summary JSON
mutmut results > artifacts/mutation/mutmut-results.txt
python scripts/parse_mutation_score.py
```

### Environment Requirements

- **Linux / macOS**: Runs directly (requires `fork()` support).
- **Windows**: Requires WSL. mutmut depends on `fork()`, which native Windows Python does not support.

## CI Integration

The workflow at `.github/workflows/mutation.yml` runs:

- On every push to `main`
- On every pull request targeting `main`
- Every Monday at UTC 06:00 (scheduled)
- On manual dispatch via `workflow_dispatch`

It uploads `artifacts/mutation/` as a build artifact containing:
- `mutmut-results.txt` -- raw mutmut output
- `mutation-summary.json` -- parsed score with pass/fail status

## Excluded Modules

The following modules are excluded from mutation testing and not counted toward the score:

| Module | Reason |
|--------|--------|
| `squad_runtime/api.py` | FastAPI route definitions, not business logic |
| `squad_runtime/cli.py` | Typer CLI entry point |
| `squad_runtime/web/` | Frontend static files |
| `squad_runtime/models.py` | Pure dataclasses/Pydantic models |
| `squad_runtime/mock_agents.py` | Test helpers |
| `squad_runtime/__main__.py` | Module entry shim |
| `scripts/` | Auxiliary scripts |

## mutmut 3.x Migration Plan

Current version is pinned to `>=2.4,<3` to preserve the `paths_to_mutate` workflow.
When migrating to mutmut 3.x, a dedicated PR should include:

1. Migrate `paths_to_mutate` -> `source_paths` in `pyproject.toml`
2. Update CI workflow commands for any CLI changes
3. Re-run mutation testing to re-establish baseline score
4. Re-confirm the excluded module list
5. Update this documentation with the new configuration
