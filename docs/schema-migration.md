# Event Hash Chain -- Schema Migration

## Schema Versions

| Version | Status | Description |
|---------|--------|-------------|
| 1.0 | Legacy | Original runtime log format. No event hash chain, no canonicalization spec version. |
| 2.0 | Current | Adds `migrationReport` for migrated archives. Events retain original fields only -- hash chain is never fabricated. |

## Migration Process

The `SchemaMigrationEngine` in `squad_runtime/schema_migration.py` handles version detection and migration:

1. Reads `schemaVersion` from the top-level payload (falls back to `run.schemaVersion` / `run.schema_version` for legacy payloads).
2. For v1.0 archives, applies `migrate_v1_to_v2()` which:
   - Sets `schemaVersion` to `"2.0"`
   - Adds a `migrationReport` documenting the migration
   - Strips any hash chain fields that may have been injected (canonicalization freeze)
   - Preserves all original data (run, nodes, events, agentResults, gates) unchanged
3. For unknown versions, returns a report with `failureClass: "CONFIG_ERROR"`.

## Historical Archives Without Hash Chain

v1 archives do not contain `previousEventHash`, `eventPayloadHash`, or `eventHash` on events. The migration **never fabricates** these values. This is the **canonicalization freeze rule**: historical data must not be retroactively augmented with cryptographic claims it never had.

After migration, the `migrationReport` records:
- `eventHashChain: "unavailable-in-v1"`
- `tamperDetection: "not-available-for-historical-events"`
- `allowedModes: ["re-evaluation", "state-reconstruction-with-warning"]`
- `disallowedModes: ["tamper-proof replay"]`

## Canonicalization Freeze Rule

When migrating an archive from a schema version that did not include event hash chains:

1. **Do not fabricate hashes.** Adding `eventHash` or `eventPayloadHash` to historical events would create false tamper-evidence.
2. **Record the limitation.** The `migrationReport` explicitly marks hash chain availability and allowed replay modes.
3. **Restrict replay modes.** Migrated v1 archives can be used for re-evaluation and state reconstruction (with warning), but not for tamper-proof replay.

## Usage

```python
from squad_runtime.schema_migration import SchemaMigrationEngine, migrate_v1_to_v2

engine = SchemaMigrationEngine()

# Direct migration
migrated = migrate_v1_to_v2(v1_payload)

# With validation
result = engine.validate_or_migrate(payload)
if result.get("failureClass") == "CONFIG_ERROR":
    # Unknown schema version
    ...
```

---

## Event Hash Chain (Canonicalization Spec v1.0)

The event hash chain provides tamper-evident ordering and content integrity for
Squad Runtime event streams. Each event carries three hash fields:

| Field                | Description                                                      |
|----------------------|------------------------------------------------------------------|
| `previousEventHash`  | The `eventHash` of the preceding event (or GENESIS_HASH for the first) |
| `eventPayloadHash`   | SHA-256 of the canonical JSON payload                            |
| `eventHash`          | SHA-256 of `(previousEventHash + eventPayloadHash)` concatenated |

### GENESIS_HASH

The chain root is the SHA-256 of the empty byte string:

```
sha256-e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

### Canonical JSON Serialization

Payloads are normalized before hashing:

1. **JSON**: `json.dumps(ensure_ascii=False, sort_keys=True, separators=(',', ':'))` encoded as UTF-8.
2. **Text values**: NFC Unicode normalization, trailing whitespace stripped per line.
3. **Paths**: Backslash `\` replaced with forward slash `/`.

These rules ensure deterministic byte output regardless of insertion order or
platform-specific Unicode handling.

### How the Chain Works

```
Event 0:  previousEventHash = GENESIS_HASH
           eventPayloadHash = sha256(canonical_json(payload_0))
           eventHash        = sha256(GENESIS_HASH + eventPayloadHash_0)

Event N:  previousEventHash = eventHash_{N-1}
           eventPayloadHash = sha256(canonical_json(payload_N))
           eventHash        = sha256(previousEventHash + eventPayloadHash_N)
```

Any modification to a payload, deletion of an event, or reordering of events
breaks the chain and is detectable by re-computing from GENESIS_HASH forward.

### Database Schema

Three nullable TEXT columns were added to `squad_events`:

```sql
ALTER TABLE squad_events ADD COLUMN previous_event_hash TEXT;
ALTER TABLE squad_events ADD COLUMN event_payload_hash TEXT;
ALTER TABLE squad_events ADD COLUMN event_hash TEXT;
```

These columns are nullable for backwards compatibility with v1 databases. The
`EventStore` adds them automatically on first open via `_ensure_hash_columns()`.

### Archive Manifest

Archives produced by `ArchiveService` now include:

```json
{
  "canonicalizationSpecVersion": "1.0",
  "eventHashAlgorithm": "sha256",
  "finalEventHash": "sha256-..."
}
```

`finalEventHash` is computed from the actual database chain rather than scanning
for an `event_hash_chain_sealed` event.

### Verifying Chain Integrity

```python
from squad_runtime.event_store import EventStore

store = EventStore(squad_dir)
result = store.verify_chain("run-1")
# result = {"valid": True/False, "eventCount": N, "finalEventHash": "...", "errors": [...]}

from squad_runtime.replay import ReplayEngine

engine = ReplayEngine()
state = engine.reconstruct_state(full_data_log_path)
# state["chainVerification"]["valid"] tells you if the chain is intact

from squad_runtime.canonicalization import verify_event_hash

# For a single event:
ok = verify_event_hash(previous_hash, payload, expected_payload_hash, expected_event_hash)
```
