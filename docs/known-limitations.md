# Known Limitations

## Environment Dependencies

- Scene F (real provider) requires `claude` CLI installed and authenticated
- Symlink tests require POSIX or Windows with symlink permissions
- Mutation testing requires `mutmut` package

## Architecture Decisions

- `squad run` is lead-only by design; full-team orchestration uses `scripts/smoke_dispatch.py`
- Event hash chain is available for new archives; historical archives without chain cannot claim tamper-proof
- Tool loop max rounds defaults to 5; configurable per profile
- Schema migration v1 to v2 does not fabricate historical event hashes

## Platform Notes

- Windows: symlink creation may require elevated permissions
- Windows: some path boundary tests use forward-slash normalization
