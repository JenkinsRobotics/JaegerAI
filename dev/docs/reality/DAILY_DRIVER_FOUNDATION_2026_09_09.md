# Daily-driver foundation: September 9, 2026

Scope: harden the existing standalone Jaeger implementation without adding a
new orchestration framework or changing Roundtable modes. Architecture and
operator commands are in [the foundation guide](../../../docs/DAILY_DRIVER_FOUNDATION.md).

## Repairs

1. **Task-board durability.** The existing JSON board performed unlocked
   read/change/write operations and treated corrupted data as an empty board.
   Updates now hold an advisory lock across the whole transaction, write a
   private temporary file, fsync it, replace atomically, and sync the directory.
   Corrupt or structurally invalid existing data is preserved and reported.
   Dependency-cycle validation is part of the same locked transaction.
2. **Focus result durability.** Reports are committed to SQLite before board
   projection. A board failure leaves a pending report instead of claiming the
   native turn failed. Later Jaeger profile turns retry pending projections;
   this never replays the original action. Projection is serialized to avoid
   duplicate cards. Confirmed native cancellations retain partial reports.
   Cards explicitly identify themselves as turn results, not verified missions.
3. **Memory growth.** The live state database was approximately 27 GiB.
   Inspection found repeated `said` belief projections whose recent value and
   evidence-list payloads totaled approximately 1.2 MB per copy. Each turn
   rebuilt scalar beliefs from accumulated conversation events. Event predicates
   now remain claims/history and are excluded from scalar belief revision and
   contradiction detection. The SQLite projection filters those events before
   loading claims, reuses unchanged beliefs, and commits actual replacements
   atomically. The in-memory implementation follows the same contract.
4. **Honest, bounded diagnostics.** Doctor checks board structure and native
   `state.db` / `dispatcher.sqlite3`, with a two-second SQLite scan budget.
   Exceeding that budget reports unknown, not success or corruption. Missing
   legacy JSON imports are no longer described as missing native memory.
   Recovery guidance preserves existing data instead of suggesting an empty reset.

## Verification

- Full root suite after the foundation/memory changes: **3,839 passed, 1 skipped**,
  one existing Discord `audioop` deprecation warning, 113.72 seconds.
  Evidence: `/tmp/jaeger-foundation-final.log`.
- Memory-store contract, belief revision, executive, and preflight regression
  tests: **63 passed**. Evidence: `/tmp/jaeger-foundation-memory-final.log`.
- Bridge tests including terminal Focus reporting through board failure:
  **92 passed**. Evidence: `/tmp/jaeger-foundation-bridge.log`.
- Tests exercise four competing real processes and eight threads, preserve all
  added cards/comments, inject atomic-replace failure, and reject malformed
  boards without replacing their contents.
- CLI help and host-service restart exited successfully. Status reports the
  bridge, adapters, gateways, desktop, and both existing containers running;
  Ollama is reachable. Containers were not recreated.
- Live native Dispatcher/Focus probe passed with actual `read_file` tool events,
  durable board projection, and subsequent Dispatcher recall. Native runs:
  `1c7c1a74166c481480448c0c01fc203e`,
  `20b69baf9c3749c79e59e6c918ece8cc`,
  `e1d85563a6324a7188db038b79afea8d`.
  Evidence: `/tmp/jaeger-foundation-live.log`.
- The historical `said` belief count and latest row stayed unchanged during
  the live verification after restart. Existing historical projections were
  not deleted. The state database is still large; this change prevents the
  identified growth path rather than reclaiming its historical disk space.
- Real WebUI API streaming and saved-session checks passed two turns for all
  four profiles: Hermes `8a8bfb770d85`, Jaeger `b76682c053db`, OpenClaw
  `448b70` (session prefix), and Roundtable `b03b7e1663cf`. The Roundtable check
  requires each first-round member to return the requested check word, not just
  the chair or an echoed question. Evidence: `/tmp/jaeger-foundation-webui.log`.
  No screenshots were used.
- A full read-only SQLite quick check passed during investigation. The final
  routine doctor run correctly reports that this large store exceeds its
  two-second scan budget. Evidence: `/tmp/jaeger-foundation-doctor.log` and
  `/tmp/jaeger-foundation-doctor-final.log`.
- `git diff --check` passes. The Hermes WebUI submodule remains clean. Existing
  user changes and staged reference-image deletions were preserved; nothing was
  committed or staged by this pass.

## Operational boundaries

The existing native-panel extension still requires upstream WebUI login and
extension consent. No credentials or permissions were changed. Focus turns
remain serialized by the current bridge; simultaneous voice/background work
is not claimed. OpenClaw model-change permissions and broader panel parity
remain as documented in the earlier profile audit. No avatar, additional
runtime integration, or new Roundtable interaction was introduced.

Board backup before restart:
`.jaeger_ai/instances/jaeger/backups/foundation-20260909-021858/board.json`.
No history, memories, workspace packages, or test suites were deleted.
