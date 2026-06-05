# Runbook

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
squad run "Ship the MVP"           # Create a new run
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
docker compose up -d
curl http://127.0.0.1:8765/api/health
docker compose down
```

## Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| 401 on API calls | Missing/invalid token | Check `squad token show` |
| `database is locked` | Multiple processes | Ensure single Runtime instance |
| `provider_blocked` event | CLI not found | Run `squad agents doctor` |
| Coverage below baseline | Test regression | Run `pytest --cov` to find gaps |
| Node stuck in `BLOCKED` | Upstream failure | Check `squad eval-gates` |
