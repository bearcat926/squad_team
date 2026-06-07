# Chain Builder Versioning

The runtime chain graph and event hash chain must record builder versions.

Required fields:

- `chainBuilderVersion`
- `chainGraphHash`
- event hash algorithm version
- snapshot manifest schema version
- frozen profile hash

Versioning allows old archives to remain replayable when future builders change
edge extraction, canonicalization, or hash algorithms.
