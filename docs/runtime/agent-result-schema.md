# AgentResult Schema

`AgentResult` is the only professional-agent completion contract accepted by
the runtime. Phase 0 records the v1 fields and the required `schemaVersion`
design gap.

## Current v1 shape

- `taskNodeId`
- `agentId`
- `status`: `pass`, `fail`, or `blocked`
- `summary`
- `evidence`
- `artifacts`
- `risks`
- `nextActions`
- `confidence`
- `workedAgainstCheckpoint`
- `agentContractVersion`

## Required schemaVersion extension

Later phases must add a typed `schemaVersion` to submitted results and to the
stored fact table. The runtime must validate provider metadata before inserting
the result as a fact.

Required provider metadata:

- `provider_used`
- `provider_type`
- `provider_identity_verified`
- `provider_fallback_triggered`
- `fallback_reason`
- `promptHash`

An AgentResult file is not trusted just because it exists in a dispatch
directory. Runtime validation must check schema, checkpoint, provider metadata,
artifact paths, and task ownership before persistence.
