# Master build status

Handoff for future agents. Resume here; do not restart Phase A.

## 2026-08-24 completion pass

- Durable turns checkpoint every finalized non-read tool transcript entry, including ordinary writes, not only external effects.
- Intake deterministically links mentions of known person entities; it does not guess new people.
- `TurnExecutive` records observed tool results and system responses as autobiographical claims, and its evidence-first contradiction gate asks for clarification before model/tool execution.
- ARES enriches character summaries through Jaeger's detail bridge, projects commitments/runs read-only, exposes wake keys and explicit event delivery, and owns no runtime rows.
- CI covers the Jaeger agent package and ARES frontend/ownership gates without models or GPU requirements.
- Implementation commits: JaegerAI `f7bd427`, `e8c0fd1`, `1508201`; ARES `7c30f7846`, `7a02bf5d9`, `3e6172007`.
- Verified: Jaeger package `579 passed`; combined Jaeger `3819 passed, 11 skipped`; ARES controller `5634 passed, 91 skipped, 1 xfailed, 2 xpassed, 16 subtests`; frontend `61 passed`; ownership guard passed.

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
  is bound. `my X is Y` is extracted into a structured claim.

### Phase E (slice) — belief revision
- `revise_group` ranks provenance. Same-rank conflict → `CONTRADICTED`.
- Observed outranks a later told claim. ADR 0006.
- `EvidenceFirstPlanner`: contradiction or high uncertainty → gather evidence.

### Phase B remainder (slice)
- External tools checkpoint via `set_effect_checkpoint`.
- `drive_one_turn` and `DefaultAgentRuntime` both use `TurnExecutive`
  when `state.db` is bound.

## IN_PROGRESS

- Mid-turn crash still loses non-external tool progress in `messages`.
- Entity extraction beyond `my X is Y`.
- ARES wait/blocked surface beyond Goals effects.

### Personas (audit)
- Four bundled `character/v1` sheets: systems_principal, research_strategist,
  robotics_architect, reliability_auditor. ARES does not own them.
- `~/.ares/prime_archetypes.json` and `~/.ares/memories/SOUL.md` remain
  unregistered drafts; ARES does not read them.

### ARES image ingest
- Screenshot upload is inspected locally (size/format). Does not open
  Jaeger `state.db`. `ARES_NO_JAEGER=1` keeps the live SI untouched.

## NEXT

- Memory consolidation and autobiographical log.
- Personal-data ingestion and capability routing.
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

- Package suite: 576 passed.
- Combined packages-then-dev: 3814 passed, 11 skipped.
