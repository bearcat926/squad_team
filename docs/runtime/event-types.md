# Runtime Event Types

All runtime events must carry a `schemaVersion` once typed event schemas are
introduced. Phase 0 records the current event surface and the schemaVersion
gaps that later phases must close.

## critical events

Critical events are durability and gate-relevant facts:

- `node_status_changed`
- `run_status_changed`
- `dispatch_started`
- `dispatch_completed`
- `directive_recorded`
- `decision_applied`
- `gate_decision`
- `gate_status_changed`
- `agent_unavailable`
- `progress_timeout`
- `cancel`
- `stale`
- `invalid_agent_result`
- `transition_conflict`
- `provider_rate_limit_wait`
- `provider_rate_limited`
- `provider_blocked`

## high-frequency events

High-frequency events are audit and observability facts:

- `agent_progress`
- `agent_heartbeat`
- `tool_call`
- `agent_operation`
- `agent_message`
- `data_flow`
- `artifact_produced`
- `coverage_lane_update`
- `role_boundary_check`
- `skill_usage`
- `mvp_file_change`
- `verification_result`

## Phase 0 gap

Current events are JSON payloads without a registry-enforced `schemaVersion`.
Phase 4 and Phase 5 must treat events as audit data unless a typed schema and
hash chain prove the payload.
