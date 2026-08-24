# Master build status

Handoff for future agents. Resume here; do not restart Phase A.

## COMPLETED

### Phase A — baseline + modular architecture
- Ports: `ProviderAdapter`, `MemoryStore`, `KnowledgeStore`, `CommitmentStore`,
  `RunStore`, `EffectLedger`, `ToolExecutor`, `ScheduleStore`.
- Schema v3 commitments, v4 runs/checkpoints/effects, v5 knowledge.
- One-instance bridge flock; AF_UNIX NDJSON v1; ARES does not open `state.db`.
- Registry isolation; effect settlement CAS; `LedgerToolExecutor` is the
  **production default** on `JaegerAgent`. Keys include durable `run_id`.
- Validation of external tools happens before the ledger claim.
- Bridge verbs: runs, commitments, effects, `deliver_event`, resolve/abandon.
- ARES Goals page projects indeterminate effects; onboarding is not a second SI.
- ADRs 0001–0005.

### Phase B (slice) — durable run identity
- `JaegerAgent.run_id` / `bind_run`.
- `TurnExecutive` binds a `turn-loop` commitment + active run, heartbeats,
  checkpoints halt/iteration cursor. The model does not decide those.

### Phase C (slice) — told-claim intake
- User turn text is recorded as `ProvenanceKind.TOLD` when a claim store
  is bound. Not last-write-wins facts. DefaultAgentRuntime uses
  `SqliteKnowledgeStore` when `state.db` is bound.

## IN_PROGRESS

- Phase B remainder: wait/blocked product surface on ARES beyond Goals effects;
  resume-after-process-death of a mid-turn loop (checkpoint is written after
  the turn, not after each tool).
- Phase C remainder: belief revision from claims; entity extraction;
  claims are recorded, not yet reconciled into beliefs.

## NEXT

- Checkpoint after each external tool, not only after the turn.
- Inject `TurnExecutive` at `AgentRuntime.agent_for` / `runtime_bridge`.
- Personal-data ingestion and capability routing (later phases).
- GitHub Actions against this tree.

## BLOCKED

- None.

## DEFERRED

- `LedgerToolExecutor` wrapping every `write` tool (too coarse; only `external`).
- Scheduler calling `deliver_event` on cron fire (cron starts a new turn today).

## REMOVED

- Stale ARES-spawned bridge holding `state.db` without the flock.

## MIGRATED

- Session todo scratchpad remains in-process; durable intentions are `commitments`.

## EXPERIMENTAL

- ARES `core/si` flag-gated; not the SI.

## KNOWN_DEBT

- GitHub Actions has not run.
- ARES `core/si` not deleted.
- Donor “Hermes/Companion” strings may remain outside onboarding.
- In-turn crash after an external effect is ledger-safe; in-turn crash
  *before* checkpoint still loses loop progress (tool results are in
  `JaegerAgent.messages` only).

## Tests (last verified)

- Package suite: 563 passed.
- Combined `packages/jaeger-agent/tests` then `dev/tests`: 3800 passed,
  11 skipped. One session-finish isolation warning on live
  `state.db-shm` (operator instance WAL), not a test failure.
