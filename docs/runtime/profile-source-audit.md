# Profile Source Audit

Profile source audit records where the frozen resolved profile came from.

Required fields for each source profile:

- path
- `commitHash`
- `contentHash`
- `schemaVersion`
- merge order

The `sourceProfiles` list must be stored with the run so acceptance can prove
which policy produced the required evidence and gates.
