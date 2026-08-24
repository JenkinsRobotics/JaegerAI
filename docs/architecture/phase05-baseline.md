# Phase 0.5 — JaegerAI side

Full record: `~/GitHub/ARES/docs/architecture/phase05-baseline.md`.

> **Correction.** An earlier revision called Phase 0.5 complete. That was
> wrong. This file records what is actually true after the lock-race
> fixes. **Architecture refactor: NO-GO** until ARES's full suite is
> green after the ctl.sh port pin, GitHub Actions has seen the tree, and
> a product `./start.sh` bridge holds the instance flock and publishes
> `bridge.sock`.

## JaegerAI suite (this tree, after lock/slot fixes)

```
.venv/bin/python -m pytest dev/tests packages/jaeger-agent/tests -q
3605 passed, 11 skipped, 0 failed    79 s    2026-08-24T02:31Z
SHA 92b9513  branch chore/monorepo-absorb  working tree dirty
```

## Bridge

- Lock loss is terminal.
- Attach socket is published only after the flock is held.
- **Empty-PID flock race:** unlinking a lock file whose holder had not
  yet written its pid created a second inode and two owners. `acquire()`
  now refuses that case. Spawn-N uses `python -m jaeger_ai.interfaces.bridge`
  with `JAEGER_TEST_LOCK_ONLY` (dummy client, real flock). 3 consecutive
  passes.
- Same empty-file race in `process_slot.acquire_slot_exclusive`: empty
  pid file is retried, not unlinked.
- After `./start.sh`, ARES still spawns one stdio bridge child that
  **does not** hold `ares/.lock` and **does not** accept on `bridge.sock`.
  Count is 1. Multi-client AF_UNIX attach is not proven on the live
  ARES-spawned process.

## Schema / FK

Ordered `_MIGRATIONS` in `sqlite_store._ensure_schema`. Live `state.db`
not migrated during this work; WAL-safe backups taken. FK pragma is
per-connection; factories that declare FKs already enable them.

## Not done

No commits. User in-flight protocol (`streaming` / `delta` / `reasoning`)
and `project_root` work is unbundled.
