# Failure Severity Strategy

Failure severity determines whether a Gate is blocked, warned, or allowed to
continue.

## Severity levels

- `blocking`: Gate must fail or block.
- `warning`: Gate may pass, but acceptance report must list the risk.
- `advisory`: recorded for traceability only.

## Default Gate mapping

- Provider authenticity failures: `blocking`
- Evidence authenticity failures: `blocking`
- Missing optional smoke artifacts: `warning`
- Coverage below baseline: `blocking`
- Provider rate-limit after retry: `blocking`
- Stale advisory after completed replacement path: `advisory`

Scenario profiles may relax warning/advisory behavior but cannot relax
security, provider authenticity, or evidence tampering failures for release
scenarios.
