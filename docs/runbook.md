# Squad Runtime Runbook

## Quick Reference

### Lead-Only Planning (CLI)

```bash
squad run "task description"
```

- Creates a single squad-lead planning node
- Suitable for task planning, decision capture, lead-only workflows
- Does **NOT** dispatch all 10 agents
- Default provider is `fake_cli`; override with `--provider`

### Full-Team Smoke (Script)

```bash
python scripts/smoke_dispatch.py --provider fake_cli --rounds 2
```

- Creates all 10 agent nodes
- Dispatches each agent through the provider
- Used for comprehensive runtime validation
- Requires `SQUAD_RUNTIME_HOME` and `PYTHONPATH` setup

### Scene F Real Provider

```bash
python scripts/smoke_dispatch.py --provider claude_cli --scenario scene-F
```

- Uses real LLM provider (claude CLI)
- Requires `claude` CLI to be installed and authenticated
- Falls back to `environment_blocked` if unavailable

## Environment Setup

| Variable | Purpose |
|----------|---------|
| `SQUAD_RUNTIME_HOME` | Path to squad-runtime source |
| `PYTHONPATH` | Must include `SQUAD_RUNTIME_HOME` |
| `SQUAD_ACCEPTANCE_ROOT` | Override project root for acceptance runs |

## Starting the Server

```bash
squad start
# or
squad start --host 127.0.0.1 --port 8765
```

Server runs at `http://127.0.0.1:8765`. Web UI at `/`.

## Creating a Run

```bash
squad init                          # Initialize .squad directory
squad run "Ship the MVP"           # Create a new run (lead-only planning node)
squad status                        # List all runs
```

## Dispatching Work

```bash
squad dispatch <run_id>             # Dispatch all ready nodes
squad dispatch <run_id> --once      # Dispatch one node
squad dispatch <run_id> --provider fake_cli  # Use specific provider
```

## Gate Evaluation

```bash
squad eval-gates <run_id>           # Evaluate all gates
squad eval-gates <run_id> --gate test_gate  # Evaluate one gate
```

## Token Management

```bash
squad token show                    # Print current token
squad token rotate                  # Generate new token
```

## Backup & Restore

```bash
squad backup backup --output backups/squad-backup.tar.gz
squad backup backup --output backups/full.tar.gz --include-token
squad backup restore backups/squad-backup.tar.gz --target .squad-restored
```

## Exporting Logs

```bash
squad export-log <run_id> --output FULL_DATA_LOG.md
squad export-log <run_id> --output data.json --final
```

## Docker

```bash
# Build and start (binds to 127.0.0.1 only)
docker compose up -d

# Health check (Python urllib, no curl dependency)
docker compose exec -T squad-runtime python -c \
  "import urllib.request; print(urllib.request.urlopen('http://localhost:8765/api/health').read().decode())"

# View logs
docker compose logs -f squad-runtime

# Stop and remove volumes
docker compose down -v
```

The container runs as non-root user `appuser`. The `.squad` directory is stored in a named Docker volume `squad-data`.

### Docker Notes

- Port 8765 is bound to `127.0.0.1` only (not exposed to external networks).
- The healthcheck uses Python `urllib` because the `python:3.11-slim` base image does not include `curl`.
- Token is **not** baked into the image. Mount or set via environment at runtime.

## Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| `provider_blocked` | claude CLI not found or not authenticated | Run `squad agents doctor` |
| `environment_blocked` | Required tools not available in CI | Verify environment setup |
| 401 on API calls | Missing/invalid token | Check `squad token show` |
| `database is locked` | Multiple processes | Ensure single Runtime instance |
| Coverage below baseline | Test regression | Run `pytest --cov` to find gaps |
| Node stuck in `BLOCKED` | Upstream failure | Check `squad eval-gates` |
