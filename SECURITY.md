# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x | Yes |

## Reporting a Vulnerability

Report security issues privately. Do **not** open a public GitHub issue.

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact

## Security Measures

### Authentication
- All API endpoints require `X-Squad-Token` header
- Token is a 32-byte URL-safe random string
- Constant-time comparison via `secrets.compare_digest`

### File Security
- Token and database files created with 0600 permissions (POSIX)
- Path traversal protection on all artifact/dispatch paths
- UNC path and Windows reserved name rejection

### Environment Isolation
- Provider subprocesses receive a filtered environment
- Cloud credentials (`AWS_*`, `AZURE_*`, `GCP_*`) blocked by default
- Database credentials (`DATABASE_*`, `POSTGRES_*`, `MYSQL_*`) blocked
- Only provider-declared variables are passed through

### Data Protection
- Events and exports are scanned for sensitive patterns
- API keys, tokens, and passwords are redacted before storage/export
- Supports: `sk-*`, `AKIA*`, Bearer tokens, JWTs, GitHub tokens
