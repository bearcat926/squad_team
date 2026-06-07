# Canonical Event Payload

Canonical event payloads prevent equivalent JSON from producing different
event hashes.

## canonical JSON

Rules:

- UTF-8
- sorted object keys
- no insignificant whitespace
- NFC-normalized strings
- LF line endings
- explicit `schemaVersion`

The resulting payload bytes are hashed into `payloadHash`, then included in the
event hash chain.
