# Mutation Testing

## Running

```bash
pip install -e ".[dev]"           # installs mutmut>=2.4,<3
mutmut run --paths-to-mutate \
  "squad_runtime/state.py" \
  "squad_runtime/gate_engine.py" \
  "squad_runtime/security/" \
  "squad_runtime/services/" \
  "squad_runtime/repositories/" \
  "squad_runtime/providers/" \
  "squad_runtime/event_store.py"
mutmut results
```

## Environment Requirements

- **Linux/macOS**: Runs directly (requires `fork()` support).
- **Windows**: Requires WSL. mutmut depends on `fork()`, which native Windows Python does not support.

## Target

- Mutation Score ≥ 60%

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

## CI

Runs every Monday UTC 06:00 on Ubuntu via `.github/workflows/mutation.yml`.
Can also be triggered manually via `workflow_dispatch`.

## mutmut 3.x Migration Plan

Current version is pinned to `>=2.4,<3` to preserve the `paths_to_mutate` workflow.
When migrating to mutmut 3.x, a dedicated PR should include:

1. Migrate `paths_to_mutate` → `source_paths` in `pyproject.toml`
2. Update CI workflow commands for any CLI changes
3. Re-run mutation testing to re-establish baseline score
4. Re-confirm the excluded module list
5. Update this documentation with the new configuration
