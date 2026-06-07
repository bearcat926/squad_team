# Squad Runtime Phase 0-6 Acceptance Report

Date: 2026-06-07

## Conclusion

`PASS_WITH_RISKS`

The Phase 0-6 core runtime hardening path is implemented and verified for the
current local MVP scope:

- Phase 0 baseline, runtime fact docs, schema registry skeleton, and golden fixtures are present.
- Phase 1 EvidencePolicy and frozen resolved profile evaluation are integrated into AcceptanceReporter.
- Phase 2 content-addressed snapshot manifest, canonicalization, boundary checks, and base/result snapshot metadata are present.
- Phase 3 ControlledToolAdapter enforces role tools, path policy, forbidden `.squad` access, tool events, and snapshot-bound writes.
- Phase 4 GateEngine supports legacy mode and strict fact-driven gates.
- Phase 5 archive manifest, replay reconstruction, schema migration report, environment fingerprint, and observability metadata are present.
- Phase 6 real-project runtime exercise generated a local project, role artifacts, tool-driven file changes, test/lint/scan facts, strict gates, FULL_DATA_LOG, archive, and archive manifest.

## Verification Summary

| Check | Result |
| --- | --- |
| Full tests | `253 passed, 4 skipped` |
| Coverage | `92.73%` |
| Coverage threshold | `>= 90%`, passed |
| Ruff | passed |
| Black | passed |
| MyPy | passed |
| Phase 6 pass rate | `100%` |
| Phase 6 strict gates | `9/9 pass` |
| Codebase Memory index | indexed |
| Codebase Memory project | `E-Project-squad-runtime-index-mirror` |
| Codebase Memory graph | `6125 nodes / 11630 edges` |
| Architecture query | non-empty |

## Commands Run

```powershell
python -m pytest tests -q
python -m pytest tests -q --cov=squad_runtime --cov-report=term-missing
ruff check squad_runtime tests scripts
black --check squad_runtime tests scripts
mypy squad_runtime
python scripts\phase6_real_project_runtime.py artifacts\phase6-real-project-runtime
```

## Phase 6 Evidence

- Run ID: `run-875b5cebfd4a`
- Summary: `artifacts\phase6-real-project-runtime\artifacts\summary-phase6.json`
- Full data log: `artifacts\phase6-real-project-runtime\artifacts\FULL_DATA_LOG-phase6.json`
- Replay state: `artifacts\phase6-real-project-runtime\artifacts\replay-state-phase6.json`
- Archive: `artifacts\phase6-real-project-runtime\project\.squad\runs\run-875b5cebfd4a\archive.json`
- Archive manifest: `artifacts\phase6-real-project-runtime\project\.squad\runs\run-875b5cebfd4a\archive-manifest.json`
- Generated project root: `artifacts\phase6-real-project-runtime\project`
- Node/React build: `exitCode=0`
- Node/React test: `exitCode=0`
- Node/React lint: `exitCode=0`

Strict gate results:

| Gate | Status |
| --- | --- |
| test_gate | pass |
| code_review_gate | pass |
| provider_authenticity_gate | pass |
| evidence_authenticity_gate | pass |
| coverage_gate | pass |
| chain_completeness_gate | pass |
| boundary_gate | pass |
| reality_checker_gate | pass |
| release_gate | pass |

## Implemented Artifacts

Primary new runtime modules:

- `squad_runtime/evidence_policy.py`
- `squad_runtime/profile_registry.py`
- `squad_runtime/snapshot.py`
- `squad_runtime/tool_permissions.py`
- `squad_runtime/tool_adapter.py`
- `squad_runtime/replay.py`
- `squad_runtime/schema_migration.py`

Primary docs and schemas:

- `BASELINE.md`
- `docs/acceptance/baseline-evidence.md`
- `docs/runtime/*.md`
- `schemas/README.md`
- `schemas/snapshot-manifest.schema.json`

Primary tests:

- `tests/unit/test_phase0_baseline_artifacts.py`
- `tests/unit/test_evidence_policy.py`
- `tests/unit/test_acceptance_evidence_gate.py`
- `tests/unit/test_snapshot_manager.py`
- `tests/unit/test_tool_adapter.py`
- `tests/unit/test_gate_engine_strict.py`
- `tests/unit/test_replay_archive_observability.py`
- `tests/acceptance/test_phase6_real_project_runtime.py`

## Risks

| Risk | Severity | Mitigation / Next Step |
| --- | --- | --- |
| Phase 6 still treats symlink-heavy as a Windows-limited profile instead of a separate full execution. Node/React and archived replay are now exercised with command evidence. | Medium | Add a dedicated symlink runner in an elevated Windows shell or POSIX CI before claiming broad filesystem-edge coverage. |
| Windows symlink negative tests are skipped because symlink creation may require elevated privileges. | Medium | Run the symlink suite in an elevated Windows shell or POSIX CI. |
| Coverage run reports existing SQLite ResourceWarning warnings in some API/service tests. | Low | Add explicit runtime close handling in the affected tests or fixtures. |
| Tool Adapter supports a controlled MVP tool set; it is not yet wired into real provider interactive tool calls. | Medium | Add provider/tool-call loop only after preserving Runtime-only state mutation. |
| Event hash chain is represented by sealed events and manifest fields; full chained hash computation for every event remains a future hardening item. | Medium | Extend EventStore with canonical event hash chaining and replay validation. |
| Schema migration engine currently validates v1 compatibility and reports failure for unknown schemas; it does not perform multi-version migrations yet. | Low | Add v1 to v2 fixture and migration transform when schema v2 is introduced. |

## Current Acceptance Position

The local MVP runtime is usable for controlled, tool-mediated project
development exercises with deterministic state ownership, evidence gates,
strict release blocking, export, archive, and replay-oriented artifacts.

It should not yet be described as a fully general multi-framework autonomous
development platform. The next hardening step is to connect the
ControlledToolAdapter to real LLM tool calls without letting agents mutate Node,
Gate, or DB state directly, and to move the remaining filesystem-edge coverage
into a dedicated symlink runner.
