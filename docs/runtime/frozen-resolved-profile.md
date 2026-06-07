# Frozen Resolved Profile

A resolved scenario profile is the merged policy that tells the runtime what
evidence, roles, gates, tools, and artifacts are required for a run.

## Freeze rule

At run start the runtime must freeze the resolved profile and store:

- `resolvedProfileHash`
- `sourceProfiles`
- source profile `commitHash`
- source profile `contentHash`
- `schemaVersion`
- active scenario type

After freeze, later edits to profile source files do not affect the run. Replay
and acceptance must use the frozen profile, not current files on disk.

## Purpose

The frozen profile prevents policy drift, accidental count hardcoding, and
post-run evidence laundering.
