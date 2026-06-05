# Development Guide

## Setup

```bash
pip install -e ".[dev]"
```

## Quality Gates

All three must pass before committing:

```bash
ruff check .         # lint
black --check .      # format
mypy squad_runtime   # type check
```

Auto-fix:

```bash
ruff check --fix .
black .
```

## Tests

```bash
# All tests (excluding real LLM)
pytest tests -q -m "not real_llm"

# With coverage
pytest tests -q --cov=squad_runtime --cov-report=term-missing --cov-fail-under=90

# Security tests only
pytest tests/security -q

# Unit tests only
pytest tests/unit -q
```

## Pre-commit Hooks

```bash
pip install pre-commit
pre-commit install
```

Hooks run `ruff` and `black` on staged files.

## Project Structure

```
squad_runtime/
  __init__.py
  cli.py                    # Typer CLI
  api.py                    # FastAPI app
  api_schemas.py            # Pydantic DTOs
  api_errors.py             # Error handlers
  runtime.py                # Facade
  event_store.py            # Dual-write event log
  gate_engine.py            # Gate evaluation
  state.py                  # NodeStatus enum + transitions
  models.py                 # Dataclasses
  adapter.py                # Agent dispatch adapter
  scheduler.py              # Dispatch candidate selection
  context.py                # Context bundle builder
  acceptance.py             # Acceptance reporter
  env_isolation.py          # Provider env filtering
  infrastructure/           # Database, schema, migrations
  repositories/             # SQL access layer
  services/                 # Business logic
  providers/                # LLM provider implementations
    base.py                 # Protocol
    impl.py                 # FakeCliProvider, LocalCliProvider
    workspace.py            # Dispatch directory management
    prompt_builder.py       # Prompt construction
    process_runner.py       # Subprocess execution
    result_parser.py        # JSON result extraction
    registry.py             # Provider plugin decorator
  security/                 # Auth, files, paths, redaction
```
