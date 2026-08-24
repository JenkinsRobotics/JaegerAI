# Phase 0 — JaegerAI side

The full cross-repository record lives in
`~/GitHub/ARES/docs/architecture/phase0-stabilization.md`. This file covers the
JaegerAI changes so the repo is self-describing; the two are kept in sync.

## Result

```
before   2 failed, 3201 passed, 11 skipped   209 s
after    0 failed, 3213 passed, 11 skipped    73 s
```

The runtime drop is not an optimisation — it is the suite no longer making
round trips to the operator's live agent.

## F5 — tests attached to the live runtime

`create_runtime()` tries `try_attach_runtime()` before `boot_for_tui`, so on any
machine with a live agent a test that patched `boot_for_tui` never reached its
patch: it proxied real turns to the operator's real brain, against real memory
and real credentials. CI has no live socket, so CI stayed green and only the
developer's machine went red. The two visible failures were the smaller half.

**Fix** — one choke point, gated by explicit configuration rather than by
monkeypatch timing.

| file | change |
|---|---|
| `jaeger_ai/core/runtime/attach_policy.py` | **new** — `JAEGER_NO_ATTACH`, mirroring the existing `JAEGER_NO_GUI` idiom |
| `jaeger_ai/core/runtime/attached.py` | `try_attach_runtime()` consults the policy first — every attach passes through here |
| `dev/tests/conftest.py` | sets the gate suite-wide; adds `bindable_instance_root` and `allow_bridge_attach` |
| `dev/scripts/run_tests.sh` | exports the gate (documented entry point) |
| `dev/tests/jaeger_ai/core/test_attach_isolation.py` | **new** — 4 tests |
| `dev/tests/jaeger_ai/core/test_attached_runtime.py` | rewritten onto the opt-in fixture |

`allow_bridge_attach` does not merely lift the gate: it first pins
`JAEGER_INSTANCE_DIR` to a disposable root and **refuses** if that root is
inside a live instance tree. The guarantee is structural, not a convention.

AF_UNIX paths cap near 104 bytes and pytest's `tmp_path` exceeds it, so the
fixtures use a short `/tmp` root — the same reason the original test hardcoded
one.

## F3 — bridge process leak and startup storm

Two behaviours in `jaeger_ai/interfaces/bridge.py` that fed each other:

1. `_boot_agent` caught the instance-flock error, emitted `fatal(kind="locked")`
   and **returned**. The transport kept serving, so a process with no agent sat
   at ~75 MB indefinitely.
2. `_start_bridge_socket` ran unconditionally, and `bsock.bind()` unlinks
   whatever file is in its way — so the loser **replaced the owner's attach
   socket**. Clients then reached a brain-less bridge, gave up, and spawned
   another, which lost the lock and hijacked the socket in turn.

Observed at discovery: 18 bridge processes, 12 reparented to PID 1, 14 spawned
inside 45 seconds, ~1.3 GB combined RSS.

**Invariant now enforced:** one instance → at most one authoritative bridge.
Many clients may attach; none creates a second long-lived bridge.

- `_Ctx` gains `exit_requested` + `inbound`; `_request_exit()` sets the event
  *and* pushes the shutdown sentinel, because the boot thread starts before
  `inbound` exists and can lose the lock on either side of that.
- Lock loss is terminal. Every **other** boot failure still keeps the transport
  alive — a model that fails to load is a degraded agent, not a duplicate one,
  and first-run onboarding runs on that transport.
- `_start_bridge_socket` probes before binding. A path that accepts a
  connection belongs to somebody; a dead file is still reclaimed, so crash
  recovery keeps working.

Tests: `dev/tests/jaeger_ai/core/test_bridge_ownership.py` (6) — no hijack of a
live socket, stale sockets still reclaimed, competing binds yield exactly one
owner, lock loss requests exit, ordinary boot failure does not, exit request
survives arriving before the queue exists. They drive the real socket helpers,
not mocks: the bug lived in what `bind` does to an existing file.

### Verification (closed in Phase 0.5)

Old leaked bridges were identified by full cmdline and terminated. Spawn-N
against a disposable instance leaves exactly one owner. Record:
`docs/architecture/phase05-baseline.md`.

## Recorded, not changed

`packages/jaeger-agent/jaeger_agent/memory/sqlite_store.py::_ensure_schema` has
a `schema_version` table and refuses a database newer than the build — good —
but its "older version → future migration runner" branch **stamps the new
version without running any migration**. A v1 database opened by v2 code is
marked migrated without being migrated. Only `_migrate_facts_table` is special
cased. Left alone in Phase 0; it needs the same ordered-runner treatment ARES
now has in `core/store/migrations.py`.

## In-flight user work

The uncommitted work on the reasoning frame, `project_root` binding and
dependency de-duplication was **not** modified, reverted, or bundled with any
Phase 0 change. In `bridge.py` the two touch non-overlapping regions: the
in-flight edits are in `_delta_frame` / `_turn_workspace` / `_turn_worker`, the
Phase 0 edits in `_Ctx` / `_boot_agent` / `_start_bridge_socket` / `main`.
Nothing was committed on the user's behalf.
