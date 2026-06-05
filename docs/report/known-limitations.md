# Known Limitations

This document records the known capability boundaries of Squad Runtime as a transparency supplement to the product-level acceptance.

## Security

| Boundary | Description | Mitigation |
|----------|-------------|------------|
| Base64/URL-encoded payload redaction | Redaction does not decode base64 or URL-encoded payloads before masking | Decoding increases false-positive rate and performance overhead; local single-user deployment has no real attack surface |
| Unicode normalization (NFKC) | Path safety does not perform Unicode normalization before validation | Local single-user deployment; attackers cannot inject malicious paths; noted for future defense-in-depth |

## Environment Isolation

Default policy does not pass through the host environment. Only a whitelist of safe variables is forwarded. See `docs/security.md` for details.

## Mutation Testing

Excluded modules are listed in `docs/mutation-testing.md`. If the first score is <60%, it does not block PR-014~017/019 merges, but **blocks the final unconditional ACCEPT**. PR-018 must achieve ≥60% by adding tests or adjusting scope.

mutmut is pinned to `>=2.4,<3` to preserve the `paths_to_mutate` workflow. Migration to mutmut 3.x requires a dedicated PR: pyproject config migration, CI workflow command migration, mutation score baseline recalculation, and excluded module list reconfirmation.

## Docker Healthcheck

The compose healthcheck uses Python `urllib` instead of `curl` because the `python:3.11-slim` base image does not include `curl`.

## Windows Symlink Tests

Windows symlink tests may be skipped due to permission requirements. Final validation relies on Linux CI coverage.

## Coverage

`security/auth.py` is a re-export compatibility layer; its coverage is not a hard quality target. The actual `token_matches` logic coverage is tracked against `security/__init__.py`.
