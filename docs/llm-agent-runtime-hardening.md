# LLM Agent Runtime Hardening Notes

## Purpose

This document captures the implemented constraints for the LLM Agent Runtime hardening pass. It is intentionally operational: every term below maps to runtime behavior or a testable boundary.

## Glossary

- **mock agent**: The old in-process `MockAgent` test helper. It is no longer the product execution path.
- **fake_cli provider**: A deterministic provider used for tests, local debugging, and phased rollout. It submits real `AgentResult` rows but is marked by `providerUsed=fake_cli` and can mark `synthetic=true` when used to fill staged dependencies.
- **deterministic provider**: Any provider whose output is stable enough for state-machine tests. In v1 this means `fake_cli`.
- **checkpoint**: The version identity that an AgentResult claims to have worked against. Snapshot mode uses a content-addressed manifest hash and excludes `.squad/`, dependency folders, build outputs, caches, and sensitive state.
- **snapshot mode**: The non-git checkpoint fallback. Runtime stores a manifest and source snapshot in `.squad/checkpoints/<checkpoint_id>/`.
- **coverage package**: A coordinated Security/SRE/Data Quality lane package. It is not test coverage; it is an auditable multi-owner risk workflow.
- **artifact**: A referenced output such as a code file, report, design note, test evidence, release manifest, or generated archive.
- **LeadDecisionChangeSet**: The Squad Lead's structured proposal. Runtime dry-runs and validates it before any state write.
- **AgentResult**: The specialist Agent's structured task result. Runtime validates checkpoint, schema, artifacts, provider metadata, and status before status changes.
- **active path**: Non-stale, non-canceled, non-replaced nodes used for Gate evaluation.
- **synthetic dependency**: A deterministic/fake result used only during phased rollout. Final all-agent acceptance must not rely on synthetic dependencies.

## RegOps Traceability

| RegOps recommendation | Implemented handling | Evidence |
| --- | --- | --- |
| Typed event schema | P0 event validation for LLM session, AgentResult submission, tool denial, Gate decision, artifact, provider fallback | `Runtime._validate_typed_event`, CLI bad-payload test |
| First-class role nodes | Agent registry snapshots 10 active runtime agents and `squad run` creates a Lead planning node | `AgentRegistry.default`, CLI run/list tests |
| Gate automatic evaluation | `squad eval-gates` and dispatch loop call `GateEngine.evaluate_all`; Gate reads fact tables first | `GateEngine`, gate fact-source tests |
| Browser smoke readiness | UI smoke remains part of final acceptance and must wait on sequence cursors | documented acceptance requirement |
| Final export metadata | `export-log --final` records `log_exported` before rendering markdown | final export test |

## Runtime Rules

- Runtime remains the only writer of Node, Gate, and DB state.
- LLM providers can only submit structured decisions/results through adapters.
- P0 events are synchronous. Non-critical audit expansion can be batched later.
- Each dispatch has an isolated LLM session, context bundle, log directory, and memory file.
- Agent memory from one dispatch is never directly reused by another dispatch; Runtime injects only structured summaries or artifact references.
- `.squad/token`, `.squad/squad.db`, `.squad/events.ndjson`, archives, and Gate/Node state files are forbidden to all Agent file access policies.

## Acceptance Shape

- Minimum real chain: Squad Lead -> one implementation Agent -> Test Engineer -> Code Reviewer -> Reality Checker.
- Full-team chain: Squad Lead + all 9 specialist Agents, with Git Workflow Master running only after Release Gate PASS.
- Final reports: `FULL_DATA_LOG.md` for facts only, `ANALYSIS_REPORT.zh-CN.md` for analysis, and an acceptance report with pass rate, coverage, risks, and codebase-memory index status.
