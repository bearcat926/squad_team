# Schema Registry

This directory is the Phase 0 skeleton for runtime schemas.

Every persisted or exported contract must declare a `schemaVersion`. Future
schema files should live here and be referenced by migrations and acceptance
replay.

Initial registry targets:

- AgentResult
- Event payload
- Snapshot manifest
- Frozen resolved profile
- Runtime chain graph
- Archive manifest

Schema changes require a migration note and a replay compatibility decision.
