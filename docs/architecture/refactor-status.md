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
  `lifecycle.py`, schema **v4**. ADR 0002 accepted.
- **Agent 2 merged as schema v5** (`e40a949`): `KnowledgeStore`. ADR 0003.
- **Agent 3 merged** (`8d32aab81` on ARES `main`): six-step onboarding.
- **Agent 4** (`cf331e4` + remaining slice): `ToolExecutor`,
  `LedgerToolExecutor` for `side_effect="external"`, bridge verbs
  `list_runs` / `list_commitments` / `list_effects` / `deliver_event` /
  `resolve_effect` / `abandon_effect`. ADR 0004.
- **Agent 5**: tool-registry isolation (session-start snapshot, restore
  before and after every test). Combined `packages/jaeger-agent/tests`
  then `dev/tests`: **3792 passed**, 11 skipped, 0 registry-order
  failures (was 32). Effect settle is CAS on `pending` so a stale
  abandon cannot delete a completed claim.
- **Agent 6**: `ScheduleStore` port + in-memory and SQLite adapters.
  ADR 0005.
- ARES Goals page: resolve/abandon for indeterminate effects (Jaeger-
  owned rows). Onboarding copy no longer calls ARES a Companion SI.

## CURRENT

- Agents 1–6 landed. Combined JaegerAI suite green in the polluted
  order that previously failed.
- `LedgerToolExecutor` is the production default; `run_id` is bound on
  every turn. `TurnExecutive` persists the run when `state.db` is bound.
- External tool results checkpoint through `set_effect_checkpoint`.
- `TurnExecutive` is constructed with `SqliteKnowledgeStore`, so claims and
  belief revision participate in production turns.
- Canonical progress: `docs/architecture/master-build-status.md`.

## NEXT

- Implement the multi-dimensional/adaptive budget work prioritized in
  `prime-framework-gap-audit-2026-08-25.md`.
- Add first-class halted-turn resume controls to the ARES Dispatcher surface.
- GitHub Actions has not run against this tree.

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
