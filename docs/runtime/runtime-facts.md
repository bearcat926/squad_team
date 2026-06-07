# Runtime Facts

Runtime facts are SQLite-backed records used by GateEngine and acceptance
reporting. Event payloads are audit mirrors; they are not the primary fact
source for gate PASS.

The term `runtime facts` refers to the durable records listed below.

## Fact sets

- `agentResults`
- `evidenceItems`
- `reviewFindings`
- `reviewFindingsHistory`
- `artifacts`
- `verificationResults`
- `coverageLanes`
- `skillUsage`
- `dataFlows`
- `agentOperations`
- `agentMessages`

## Minimum fact requirements

Facts must identify author, run, task node, source, and immutable evidence
where relevant. `artifacts` and `verificationResults` must be tied to scenario
profile requirements rather than raw count thresholds.

## Current gap

Some exported facts currently come from events instead of dedicated typed fact
tables. Phase 4 must ensure GateEngine reads the fact tables or fact extractor
outputs, not raw event payloads.
