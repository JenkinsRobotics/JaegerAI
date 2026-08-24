# ADR 0002 — Runs, checkpoints and an effect ledger under commitments

Status: proposed (Agent 1 — runtime; Lead ratifies)
Date: 2026-08-23
Extends: ADR 0001 — ports, not frameworks

## Context

ADR 0001 gave unfinished SI work a durable home: a row in `commitments`
with deterministic transitions. That records **what the SI intends**.
It does not record **what happened when it tried**, so:

- a crash lost the attempt entirely — the goal survived, the progress did not;
- nothing distinguished "this never ran" from "this ran and the answer was lost";
- a resumed task would happily re-do its last step, and re-doing a step
  that sent an email is not a retry;
- `waiting_for_event` named no event, so nothing could wake it;
- an `active` commitment whose process died stayed `active` forever.

## Decision

Three tables under commitments, all in the existing `state.db`, all
written by deterministic code in `jaeger_agent/cognition/lifecycle.py`.

```text
commitment   what the SI intends          survives everything
run          one attempt at it            survives the process
checkpoint   how far that attempt got     survives the crash
effect       what it did to the world     happens at most once
```

**Runs** are attempts. One commitment accumulates many across crashes,
restarts and provider swaps, numbered by `attempt`. A run claims a
process via `owner_pid`; leaving `active` releases the claim.

**Checkpoints** are append-only progress cursors keyed `(run_id, seq)`,
written by the runtime rather than the model. They carry task progress
and nothing else — no conversation handle, no SDK object — which is what
makes resuming a Claude-checkpointed run on Gemini a configuration
change rather than a rewrite. A test asserts the cursor JSON contains no
provider identity.

**Effects** are the at-most-once ledger for authoritative side effects.
`once(key, action, fn)` claims the key, performs the effect, records the
result. The claim is a primary-key INSERT, so two processes racing the
same key cannot both proceed.

**Recovery** is a liveness question, not a judgement. `recover()` asks
the OS whether each active run's owner pid still exists and moves the
orphans to `blocked` with `reason="owner_lost"`.

### The consequential choice: indeterminate is a state

An orphaned run lands in `blocked`, not `failed`, and a crashed effect
stays `pending`. Retrying a `pending` effect raises
`EffectIndeterminate` rather than re-running it or skipping it.

The crash may have happened before or after the email left. The runtime
does not know, and a model asked "did it send?" will answer fluently
either way. So the ledger refuses and escalates to something that can
actually check, which then calls `resolve` (it landed) or `abandon` (it
did not). Silent re-execution and silent skipping are both worse than a
stop.

This is the ADR 0001 principle — the model proposes, the store decides —
extended to the case where the store's honest answer is "unknown".

## Consequences

- Schema v4 (`runtime-runs-checkpoints-effects`): three tables plus
  `commitments.parent_id`. Additive; no existing row is read or
  rewritten. Registered in the ordered `_MIGRATIONS` map, so the
  recorded version still names the schema that actually ran.
- A new runtime backend implements `RunStore` and passes
  `tests/contract/test_run_store_contract.py`; the same for
  `EffectLedger`. Both contracts run against the in-memory reference and
  the SQLite adapter in one parametrised pass, so the two cannot drift.
- Parent commitments cannot complete while a child is non-terminal.
  `cancelled` is exempt: abandoning a subtree is not a claim it finished.
- Anything performing an authoritative external action from a resumable
  run should route it through `EffectLedger.once`. Nothing enforces that
  yet — see below.

## Not decided here

- **No product surface.** No tool, bridge verb or ARES projection is
  added; that contract belongs to the Lead and Agents 3/4. The required
  shape is recorded in the Agent 1 report.
- **No scheduler.** `deliver_event(wake_key)` is the intake primitive.
  Who calls it, and on what cadence, is the scheduler port on the
  roadmap.
- **No enforcement** that side-effecting tools use the ledger. That is
  an architecture-fitness test once the tool boundary is formalised
  (Agent 4).
