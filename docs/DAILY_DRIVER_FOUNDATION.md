# Daily-driver foundation

JaegerAI owns the standalone application: persistent Dispatcher conversation,
native memory, task execution, and its interfaces. ARES is not the owner of this
development architecture. The existing agent packages remain separate internal
boundaries so they can be extracted or reused later.

## Boundaries to build on

| Responsibility | Existing implementation |
| --- | --- |
| Conversation identity and Focus reports | `jaeger_ai/core/runtime/dispatcher.py` |
| Commitments, runs, checkpoints, action receipts | `packages/jaeger-agent/jaeger_agent/cognition/` |
| Item progress and completion checks | `jaeger_ai/core/runtime/work_ledger.py` |
| External worker capabilities and lifecycle | `packages/jaeger-agent/jaeger_agent/delegates/contracts.py` |
| Native profile transport and cancellation | `jaeger_ai/interfaces/hermes_profile_adapters/` |
| Facts, claims, beliefs, and history | Native `memory/state.db` |
| Task board | Native `memory/board.json` |
| Shared interface | Pinned Hermes WebUI with Jaeger-owned extensions/adapters |

Direct Hermes, Jaeger, OpenClaw, and Roundtable profiles remain available.
Roundtable's current modes are unchanged. Future models, workers, avatars, and
robotics must extend these boundaries rather than create a competing identity,
memory store, or task authority.

This is a map of the existing foundation, not a claim that every execution path
already shares one unified scheduler. Focus conversations have separate contexts;
the current bridge still serializes their turns.

## Reliability rules

- Board updates lock the full read/change/write across threads and processes.
  Writes use private temporary files, flush to storage, and atomically replace
  the prior file. Invalid existing data raises an error and is preserved.
- A native Focus result is saved before its board projection. A failed projection
  remains pending and is retried on a later Jaeger profile turn without executing
  the original task again. Confirmed cancellations retain partial results.
- A completed Focus report means one turn finished; its board card is explicitly
  a **turn result**, not independent verification of the entire objective.
- Conversation events (`said`, `responded`, `tool_result`, `mentioned_person`)
  remain claims/history. They are not competing values of a single property and
  are excluded from scalar belief revision and contradiction detection.
- Rebuilding unchanged beliefs preserves their identity. Actual changes retain
  the prior projection as superseded history. Existing historical records are
  not deleted or compacted automatically.
- Native execution with an uncertain outcome retains ownership. A disconnected
  observer does not authorize replay, and requesting cancellation does not prove
  the worker stopped.

## Daily operation and checks

```sh
./jaeger start
./jaeger webui url --instance jaeger
./jaeger doctor
./jaeger status
```

Open the discovered WebUI address and choose the profile. In Jaeger, the pinned
Dispatcher conversation retains the operator thread; other conversations are
Focus sessions.

`doctor` checks board structure and native SQLite integrity. Routine SQLite scans
have a two-second execution budget. A large store may show **unknown / not
verified**, rather than falsely passing or delaying startup indefinitely. An
unbounded integrity scan can be performed separately during maintenance; it must
not be confused with the routine boot check.

The installed native memory/skills extension requires the WebUI's own login and
extension consent. Set the access password locally in WebUI Settings and approve
**Jaeger Dispatcher and Focus** under Extensions. This is an upstream requirement;
the application does not bypass it or grant consent automatically.

After code changes:

```sh
.venv/bin/pytest
```

The opt-in live probe below uses model tokens, creates a labeled Focus session,
reads the repository README through a real tool, and checks Dispatcher continuity
and its saved report:

```sh
.venv/bin/python scripts/verify-dispatcher-native.py
```

Actual live verification is distinct from unit tests. Do not describe all panels,
voice concurrency, or newly registered external engines as operational merely
because their imports or contract tests pass.
