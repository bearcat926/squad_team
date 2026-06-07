# Baseline Evidence

This document records Phase 0 evidence for commit `c5db505`. These values are
baseline observations, not global thresholds.

## Native Scene F

- Run ID: `run-5e18712d0c6e`
- Goal: `scene-F smoke test`
- Provider: `provider=claude_cli`
- Provider type: `real_llm`
- Synthetic dependency: `synthetic=false`
- Gate result: `gates=PASS`
- Observed nodes: `10`
- Observed AgentResults: `10`
- Observed gates: `4`

## Full Development Run

- Run ID: `run-85631d7da7da`
- Goal: `Build collaborative real-time task dashboard MVP with tenant-scoped RBAC and audit logging`
- Provider: `provider=claude_cli`
- Provider type: `real_llm`
- Synthetic dependency: `synthetic=false`
- Gate result: `gates=PASS`
- Observed nodes: `10`
- Observed AgentResults: `10`
- Observed artifacts: `13`
- Observed evidence items: `48`
- Observed verificationResults: `4`

## Evidence Root

The archived evidence root is:

`E:\Project\Multica小队\archive\2026-06-07-squad-runtime-real-run\scenario-run`

Generated fixtures under `tests/fixtures/acceptance/` intentionally store a
compact observation subset so tests remain stable and reviewable.
