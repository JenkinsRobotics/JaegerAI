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

## CURRENT

- ARES full pytest after isolation pins: **5628 passed, 91 skipped, 0 failed** (1165 s).
- JaegerAI after contract slice: see TEST RESULTS in the lead report.
- Bind commitments to a product surface (tool or query) without making
  ARES a second runtime.
- Lead Architect (this session) coordinates specialists in worktrees.

## NEXT

- Scheduler port wrapping Jaeger schedules + ARES projection.
- Retrieval port separate from MemoryStore writes.
- SELF/USER/RELATIONSHIP/WORLD projections as read models over facts
  (do not replace sqlite).
- Exercise GitHub Actions on a stabilization-only branch.

## DEPRECATED

- Treating ARES `jobs.json` as SI-authoritative when Jaeger is up.
- Unlinking an in-progress instance lock (empty PID).

## REMOVED

- Stale ARES-spawned bridge that held `state.db` without the flock.

## MIGRATED

- Commitment state: in-process todo scratchpad remains session-local;
  durable intentions go to `commitments` in `state.db`.

## KNOWN DEBT

- Full ARES suite after last isolation pins may still be running.
- GitHub Actions has not run against this tree.
- ARES `core/si` still exists, flag-gated experimental — not deleted.
- Non-English UI catalogs cleaned of Hermes; other donor strings may remain
  outside `i18n.js`.
