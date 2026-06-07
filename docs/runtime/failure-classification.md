# Failure Classification

Runtime failures must be classified with a `failureClass` so acceptance reports
can distinguish product risk, evidence gaps, provider issues, and security
violations.

## Classes

- `EVIDENCE_MISSING`
- `EVIDENCE_TAMPERED`
- `INVALID_AGENT_RESULT`
- `CHECKPOINT_MISMATCH`
- `PROVIDER_UNAVAILABLE`
- `PROVIDER_RATE_LIMITED`
- `SECURITY_VIOLATION`
- `BOUNDARY_VIOLATION`
- `DEPENDENCY_BLOCKED`
- `GATE_DEPENDENCY_FAILED`
- `ENVIRONMENT_BLOCKED`
- `RUNTIME_ERROR`

## Severity strategy

Every failureClass maps to a severity: `blocking`, `warning`, or `advisory`.
Security and evidence authenticity failures are blocking for release-oriented
scenarios. Smoke scenarios may downgrade some missing artifact facts to warning
only when the frozen scenario profile explicitly allows it.
