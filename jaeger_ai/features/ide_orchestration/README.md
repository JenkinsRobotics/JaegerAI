# IDE orchestration feature

Coordinates worker tasks through the existing Gateway surface. Current built-in
adapters launch **one-shot CLI delegates**, not existing IDE-panel conversations.
The deterministic fake adapter is a test fixture, not live product proof.

## Current guarantees and limits

- Process-local immutable request snapshots: same-key/same-request retries join
  one execution; changed goal, worker, workspace, read-only setting, budget,
  capabilities or metadata conflicts. A reused task ID with a different key
  also conflicts. Nested metadata is frozen at admission.
- Worker completion and independent verification are separate. Without a
  task-specific verifier, useful completed output remains completed and
  `verified=false`. A worker's claim cannot certify itself.
- Cancel is a no-op for terminal tasks. Active cancellation stops the operation;
  a submission interrupted before receipt is `unknown`, never blindly resent.
  Remote cancellation confirmation is reported separately.
- Gateway shutdown cancels through this service and waits for adapter cleanup
  before releasing its owner lease. A cleanup timeout is recorded as `unknown`
  with cancellation unconfirmed.
- The time deadline covers awaited probe, submit, observation and result, even
  when no progress arrives. Cleanup has a separate one-second bound. Adapters
  must cooperate with asyncio cancellation; synchronous blocking code cannot be
  forcibly stopped by this service.
- CLI probes explicitly identify their transport and cannot claim existing-panel,
  follow-up, reconciliation or read-only enforcement. Current CLI launchers do
  not enforce `read_only`, so those requests are rejected before launch.
- Availability/auth/quota failures remain visible in current task records.
  Progress events have monotonically increasing task-local sequence numbers.

Records, retry operations and adapter handles remain **in memory**. They do not
survive owner restart, and this service does not yet compose its tasks into the
existing durable owner RunStore/DelegateExecutor. Read-only is enforceable only
when a concrete adapter supplies that contract. `max_turns` and `max_cost_usd`
are request metadata, not enforced usage accounting; no pause operation exists.
Do not label this a finished orchestration or restart-safe release.

The public Gateway route currently rejects `read_only=false` with 403, while the
built-in CLI adapters cannot enforce `read_only=true`. Public CLI delegation is
therefore deliberately unusable until a server-owned authorization/verification
plan and a genuinely read-only adapter exist. Arbitrary client metadata is not an
authority or verifier. Direct in-process service callers remain available to
trusted composition/tests. This state cannot satisfy the RC7 live-worker gate.

## Existing surface

| File | Role |
| --- | --- |
| `contracts.py` | ParentTask, required capabilities, budgets, progress/results |
| `service.py` | Process-local coordination, cancellation and verification |
| `adapters.py` | CLI DelegateRuntime wrapper and deterministic fixture |
| `__init__.py` | Exports |

Gateway routes exist for GET workers, POST tasks, GET task and POST task/cancel
under `/v1/orchestration`. Create now validates and reserves the complete service
snapshot before acknowledging: exact replay returns 200, new admission 201,
conflicting reuse 409, unknown worker 404, invalid input 400. Workspace, metadata,
budgets, read-only and required capabilities are forwarded. Operations participate
in existing Gateway shutdown tracking under tuple keys distinct from ordinary
request IDs. Availability/capability execution failures remain retrievable via GET.
An operation cancelled before starting leaves a replayable cancellation record.
These HTTP guarantees are tested with isolated deterministic workers; restart
persistence and real IDE-panel transport are still unqualified.

The next slice must reuse Gateway admission/events, owner run persistence and
the existing delegate lifecycle. It must prove one actual existing IDE worker
conversation: bounded task, observed reply, same-conversation follow-up and an
independent file/test/UI result check. Reconcile uncertain delivery after owner
restart, integrate scoped UI ownership/Stop/yield, and preserve target identity.
Do not create another database, runtime, or fake worker transcript.

## Verification

```bash
dev/scripts/run_tests.sh --unit dev/tests/jaeger_ai/features/test_ide_orchestration.py
dev/scripts/run_tests.sh --integration dev/tests/jaeger_ai/features/test_ide_orchestration.py
```

The socket-based Gateway fixture is marked integration. Unit tests exercise
concurrent retries/conflicts, terminal cancellation, silent deadlines, capability
rejection, availability results and independent temporary-file verification.
These checks use isolated state and no live models, desktop input or paid calls.
