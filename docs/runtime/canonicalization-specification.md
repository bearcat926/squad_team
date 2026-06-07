# Canonicalization Specification

Canonicalization makes snapshots, event hashes, and artifact hashes stable.

## Rules

- Normalize Unicode strings to NFC.
- Normalize text line endings to LF before hashing text files.
- Normalize the path separator to `/` in manifests.
- Sort manifest files by canonical relative path.
- Hash file bytes after the declared content canonicalization step.
- Exclude non-deterministic metadata from snapshot hashes.

## Windows notes

Drive letters and UNC paths must be resolved through the workspace boundary
guard before canonical relative paths are emitted. Absolute paths must never be
used as manifest identity.
