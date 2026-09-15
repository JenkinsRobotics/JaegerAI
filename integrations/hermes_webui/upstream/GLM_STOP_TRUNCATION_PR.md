# Draft upstream PR: respect authoritative GLM `stop` results

## Problem

The truncation heuristic can classify a complete Ollama GLM response as truncated when it is
a list, path, or unpunctuated tool-assisted answer. Even with provider `finish_reason=stop`,
the agent retries the completed answer and can surface an application error after repeated
continuations.

## Proposed change

In `_should_treat_stop_as_truncated`, treat an authoritative `finish_reason=stop` from the
Ollama GLM cloud lane as terminal. Preserve recovery for `length` and other explicit token-limit
signals. Keep the existing heuristic for providers/models that do not return a trustworthy
terminal reason.

Scope the rule through existing provider/model metadata rather than patching `AIAgent` at
import time. This keeps behavior local to the provider decision and avoids changing agent
classes globally.

## Tests

- `stop` plus a complete bullet list is terminal.
- `stop` plus a filesystem path is terminal.
- `stop` plus an unpunctuated answer after tool messages is terminal.
- `length` for the same shapes still requests continuation.
- Local models and non-GLM providers retain their current policy unless their finish reason is
  already documented as authoritative.

## Jaeger transition

Jaeger removed its runtime method patch. Until an upstream release includes this provider-level
fix, the deployment should pin a reviewed fork commit rather than reinstall a monkey patch.
