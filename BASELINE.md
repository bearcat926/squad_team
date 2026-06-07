# Squad Runtime Acceptance Baseline

Baseline commit: `c5db505`

This file freezes `c5db505` as the Phase 0 acceptance baseline for the
Phase 0-6 runtime hardening plan. The baseline is an acceptance baseline and
not a global threshold. Counts captured from real runs are observations used to
detect drift and to seed tests; later scenarios may legitimately have different
artifact, event, or evidence counts when their scenario profile requires it.

## Baseline Evidence

- Native Scene F: `run-5e18712d0c6e`
- Full development run: `run-85631d7da7da`
- Provider observation: `provider=claude_cli`
- Synthetic dependency observation: `synthetic=false`
- Gate observation: `gates=PASS`

## Baseline Rule

Acceptance claims must compare against this baseline by explicit policy fields,
not by hardcoded global counts. If a future scenario needs different evidence,
the scenario profile must state that requirement before the run starts.
