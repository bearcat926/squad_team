# Testing Guide

## Directory Structure

```
tests/
  unit/                     # Fast, isolated, no DB
    providers/              # Provider component tests
    repositories/           # Repository tests
    services/               # Service tests
  integration/              # Uses real SQLite DB
    test_runtime_core.py
    test_runtime_services.py
    test_schema_initialization.py
    test_migrations.py
    test_backup_restore.py
  api/                      # FastAPI endpoint tests
    test_api_schemas.py
    test_api_errors.py
  security/                 # Security feature tests
    test_api_auth.py
    test_file_permissions.py
    test_path_safety.py
    test_provider_env_isolation.py
    test_redaction.py
  acceptance/               # Full scenario tests
    test_acceptance_runner.py
    test_real_llm_acceptance.py
  contract/                 # Public API contract tests
    test_runtime_public_api.py
```

## Pytest Markers

| Marker | Description |
|--------|-------------|
| `unit` | Unit tests |
| `integration` | Integration tests |
| `api` | API tests |
| `security` | Security tests |
| `acceptance` | Acceptance tests |
| `real_llm` | Requires real LLM provider (skip in CI) |

## Running Tests

```bash
# Default: all except real LLM
pytest tests -q -m "not real_llm"

# Only security
pytest tests/security -q

# With coverage
pytest tests -q --cov=squad_runtime --cov-report=term-missing --cov-fail-under=90

# Real LLM acceptance (requires claude CLI)
pytest tests/acceptance -q -m real_llm
```

## Coverage

Global target: **>= 90%**

Coverage is enforced in CI via `--cov-fail-under=90`.

## Mutation Testing

```bash
pip install mutmut
mutmut run
mutmut results
```

Target: mutation score >= 60%. See `docs/mutation-testing.md` for details.
