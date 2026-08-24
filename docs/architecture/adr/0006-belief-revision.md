# ADR 0006 — Beliefs are a ranked projection, not last-write-wins

Status: accepted
Date: 2026-08-23
Extends: ADR 0003 — epistemic knowledge

## Decision

Claims are authoritative. Beliefs are derived. `revise_group` ranks
provenance (system > observed > told > inferred > predicted > believed).
A later told claim cannot overwrite an observation. Two claims of the
same rank with different values produce `BeliefStatus.CONTRADICTED`
and `get_active_belief` returns none.

`rebuild_beliefs_from_claims` on both adapters calls the same reviser.
TurnExecutive rebuilds after recording user text. Structured `my X is Y`
propositions are extracted deterministically in addition to the raw
`said` claim.

## Consequences

- Contested truth stays contested until higher-rank evidence arrives.
- The model does not decide which value is believed.
