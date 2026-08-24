# Architecture refactor status

## COMPLETED

- Production SI bridge (PID recorded at runtime) holds instance flock and
  publishes `bridge.sock`; three simultaneous AF_UNIX clients accepted.
- Stale non-owner bridge (no flock) terminated.
- `MemoryStore` port + in-memory adapter + contract tests.
- `ProviderAdapter` contract tests (fake + production subclasses).
- `CommitmentStore` port, deterministic transitions, SQLite adapter,
  schema v3 migration.
- Architecture fitness: agent loop and memory facade must not import
  provider SDKs.
- ADR 0001: ports, not frameworks.
- **Agent 1 merged** (`b7f4f11`): `RunStore`, `EffectLedger`, shared
  `lifecycle.py`, schema **v4** (runs / checkpoints / effects /
  `commitments.parent_id`). Package suite **522 passed**. ADR 0002 accepted.
- Orphaned runs go to `blocked`; crashed effects stay `pending` and
  raise `EffectIndeterminate` rather than retry.
- **Agent 2 merged as schema v5** (Lead rebase of `agent2/memory-wip`):
  `KnowledgeStore` port, provenance models, SQLite + in-memory adapters,
  `KnowledgeRetriever`. v4 remains runtime; knowledge did not retake it.
  Package suite **544 passed**. ADR 0003 accepted.
- **Agent 3 merged** (`8d32aab81` on ARES `main`): onboarding is six
  implemented steps; Back from runtime returns to privacy; ARES is
  experience/governance, JaegerAI is the runtime. Frontend 61 passed.
- **Agent 4 first slice merged** (`cf331e4`): `ToolExecutor` port +
  `DirectToolExecutor`; loop injects the executor; default behaviour
  unchanged. Package suite **546 passed**. ADR 0004 accepted.

## CURRENT

- Agents 1–3 landed. Agent 4 replaceability slice landed; assigned
  runtime/bridge work is still open.
- Bind runs/commitments to a bridge verb and ARES projection (Lead +
  Agents 3/4). No product surface in Agent 1, by design.
- Agent 5 has an unmerged red-team commit (`6f8069a`, effect settlement
  race) — review separately; do not treat as complete.

## NEXT

- Agent 4 remaining: fitness test that side-effecting tools use
  `EffectLedger.once`; bridge read verb for runs/commitments;
  `deliver_event(wake_key)`.
- Agent 3: `EffectIndeterminate` needs a human resolve/abandon surface;
  remaining onboarding copy still says “Companion” in a few headings.
- Agent 5: global tool-registry order dependence (32 failures when
  `packages/jaeger-agent/tests` runs before `dev/tests`);
  `test_bench_history_verb.py::test_since_filter_excludes_old_runs`;
  review `6f8069a`.
- Agent 6: scheduler port wrapping Jaeger schedules + ARES projection.

## DEPRECATED

- Treating ARES `jobs.json` as SI-authoritative when Jaeger is up.
- Unlinking an in-progress instance lock (empty PID).

## REMOVED

- Stale ARES-spawned bridge that held `state.db` without the flock.

## MIGRATED

- Commitment state: in-process todo scratchpad remains session-local;
  durable intentions go to `commitments` in `state.db`.

## KNOWN DEBT

- GitHub Actions has not run against this tree.
- ARES `core/si` still exists, flag-gated experimental — not deleted.
- Non-English UI catalogs cleaned of Hermes; other donor strings may remain
  outside `i18n.js`.
