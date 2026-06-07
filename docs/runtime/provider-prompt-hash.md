# Provider Prompt Hash

Every real LLM dispatch must record a `promptHash`.

## Scope

`promptHash` covers:

- provider id
- agent id
- task node id
- checkpoint or snapshot id
- system role profile
- task context bundle
- tool policy summary

The provider, dispatch id, and `promptHash` must be stored with AgentResult
metadata so fallback, replay, and provider authenticity gates can trace what
the model actually received.
