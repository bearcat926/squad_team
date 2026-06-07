# Fact Coverage Matrix

| Fact | Source | Gate | Phase 0 Status |
| --- | --- | --- | --- |
| AgentResult | `agent_results` | Test, Review, Reality, Release | present |
| Evidence item | `evidence_items` | Test, Evidence Authenticity | present |
| Review finding | `review_findings` | Code Review | present |
| Artifact | `artifacts` | Evidence Authenticity, Release | present |
| Verification result | event/fact extractor | Test, Coverage | partial |
| Coverage fact | coverage report extractor | Coverage | missing typed extractor |
| Provider identity | provider doctor + dispatch metadata | Provider Authenticity | partial |
| Snapshot manifest | snapshot manager | Boundary, Chain | missing |
| Event hash chain | event store | Chain Completeness | missing |
| Frozen profile | profile registry | Evidence Gate | missing |

This matrix is an inventory, not an acceptance shortcut. Each Gate must declare
which facts it consumes and which missing facts are blocking, warning, or
optional for the active scenario.
