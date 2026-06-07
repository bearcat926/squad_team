# Event Hash Chain

The event hash chain makes runtime audit logs tamper-evident.

## Fields

- `eventHash`
- `previousEventHash`
- `finalEventHash`
- `schemaVersion`
- canonical event payload hash

## Rule

Each event hash is computed from the canonical payload plus
`previousEventHash`. Archive manifests must record the `finalEventHash`.
Reconstruction must fail or warn when the chain is missing, broken, or computed
with an unsupported chain builder version.
