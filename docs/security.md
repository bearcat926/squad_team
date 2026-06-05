# Security

## API Authentication

All `/api/*` endpoints require the `X-Squad-Token` header. Public exceptions:
`/api/health` and `/` (web UI).

```bash
curl -H "X-Squad-Token: $(cat .squad/token)" http://127.0.0.1:8765/api/runs
```

## Token Management

| Command | Description |
|---------|-------------|
| `squad init` | Creates `.squad/token` if missing |
| `squad token show` | Prints current token |
| `squad token rotate` | Generates new token, overwrites file |

Token files are written with `0600` permissions on POSIX systems.

## File Permissions

`squad_runtime/security/files.py` provides `write_secret_file()` which sets
`stat.S_IRUSR | stat.S_IWUSR` (0600) on POSIX. On Windows, the permission
call is skipped (filesystem ACLs apply).

## Environment Variable Isolation

Provider subprocesses do **not** inherit the full host environment.

| Category | Policy |
|----------|--------|
| `PATH`, `HOME`, `TEMP`, etc. | Always allowed |
| `SQUAD_*` | Always allowed |
| Provider `required_env` | Allowed if declared |
| `AWS_*`, `AZURE_*`, `GCP_*`, `DATABASE_*`, `SECRET_*`, etc. | Blocked by default |

See `squad_runtime/env_isolation.py`.

## Path Safety

All artifact and dispatch paths are validated by `security/paths.py`:

- No `..` traversal outside `.squad`
- No absolute paths escaping root
- No UNC paths (`\\server\share`)
- No Windows reserved names (`CON`, `NUL`, etc.)
- Symlink targets must also be inside root

## Event & Export Redaction

`security/redaction.py` scans for and replaces:

- `sk-*` API keys
- `AKIA*` AWS keys
- `Bearer` tokens
- JWT tokens (`eyJ...`)
- GitHub tokens (`ghp_*`, `gho_*`, etc.)
- Dict keys matching `token`, `password`, `secret`, `api_key`, etc.

Applied to event payloads and exported logs.
