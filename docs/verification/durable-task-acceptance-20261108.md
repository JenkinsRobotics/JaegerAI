# Durable task acceptance: isolated cloud verification, 2026-11-08

## Scope and production path

Work is on `fix/assistant-core-acceptance-20261108`, based on
`ff71bb769bc56e4c6d7be6d540a86be73e291e07`. No live Mac state, remote push,
merge, deployment, provider request, external message, or paid action is needed.

The shared UI's `api/gateway.ts` task proposal create/approve/cancel calls reach
`/v1/tasks` and its approval/cancellation routes in `core/gateway/server.py`.
They call `GatewayTaskOwner.submit`, `resolve`, and `cancel`. The owner's `tick`
dispatches the saved tasks through the canonical Gateway request store.
These changes therefore affect the durable Work path, not a legacy scheduler.

## Reproduced and repaired

1. Cancellation committed after the executor read its task could still admit
   and dispatch an ordinary task. Only webhook tasks previously checked saved
   cancellation inside request admission. All durable admissions now recheck
   authority, cancellation, terminal state, and attempt in the same transaction.
2. Two waiters reconciling one failed receipt consumed two retries. Settlement
   now checks terminal state and the current attempt under the task transaction.
3. Task Stop left an owned child handoff's approval pending. Task Stop now uses
   the existing qualified descendant cancellation path, including children from
   earlier yielded/retried attempts. Unknown/live children keep the task paused
   until their canonical receipts establish cessation. Unrelated/unqualified
   handoffs are never signalled.
4. Independent review caught stale cancellation settlement reopening a cancelled
   and delivered task. Terminal/attempt checks now protect that post-await write;
   a concurrent cancellation regression covers the exact interleaving.
5. Re-review found dispatch eligibility blocking cancellation reconciliation when
   a yielded task had no current receipt. Reconciliation now precedes those
   guards. Disabled/removed specialists and revoked webhooks cannot strand
   cancellation after earlier children finish. All three regressions failed
   before this fix and now pass without admitting another request.

The owner also populates the existing run history and saves request-boundary
`payload.last_progress`, `payload.next_action`, and `payload.blocker`. Newly
submitted tasks save objective/artifact/evidence completion criteria. Approval
and proposal editing update that checkpoint without changing authority policy.
Existing objective, execution scope, retry policy, cancellation intent, and
verified result remain in their canonical fields. No database migration or new
scheduler was introduced.

## Repeatable verification

Use an external venv and disposable state. From the repository root:

```sh
export HOME=/tmp/jaeger-baseline-20261108/home
export JAEGER_NO_ATTACH=1 PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX=/tmp/jaeger-baseline-20261108/cache/pycache
export JAEGER_STATE_DIR=/tmp/jaeger-baseline-20261108/durable-state
/tmp/jaeger-baseline-20261108/venv/bin/python -m pytest -q \
  dev/tests/jaeger_ai/core/test_task_execution_races.py \
  dev/tests/jaeger_ai/core/test_task_child_cancellation.py \
  dev/tests/jaeger_ai/core/test_task_owner_process_recovery.py \
  dev/tests/jaeger_ai/core/test_gateway_task_owner.py \
  dev/tests/jaeger_ai/core/test_gateway_process_recovery.py \
  dev/tests/jaeger_ai/core/test_gateway_durability.py \
  dev/tests/jaeger_ai/core/test_handoff_cancellation_tree.py \
  dev/tests/jaeger_ai/core/test_durable_tasks.py \
  dev/tests/jaeger_ai/core/test_webhooks.py \
  dev/tests/jaeger_ai/features/webhooks
```

The regression files carry their setup and expected observations. The process
recovery file launches an isolated owner, commits one local synthetic file
write, kills only that child process, then launches two independent successor
processes against the same disposable database. Completed receipts are rehashed
and delivered once; uncertain receipts and cancellation intent remain retained,
without a new request, effect, or retry. The existing process-recovery suite also
checks that a second process cannot claim a live Gateway's database lease.

Baseline owner/durable tests: **27 passed**. The two initial new race tests:
**2 failed before fixes**, then passed. Pending-child Stop regression:
**failed before fix**, then passed. Expanded suite before the final review and
prior-attempt refinements: **74 passed**. Final results are recorded below.

## Evidence boundary and remaining acceptance work

These are real SQLite, HTTP-handler, concurrent-waiter, and killed-subprocess
checks with synthetic local workers. They do **not** prove a live model/provider,
native Mac UI, full daemon restart, external provider exactly-once behavior, or
all task/tool combinations. File evidence is independently re-read and hashed;
it proves file identity/freshness, not semantic quality of arbitrary output.

Unknown effects are never replayed automatically. Known failures have the
existing three-retry cap; yielded continuations are not failures and do not
consume that cap. Last progress is a durable **request-boundary** observation,
not tool-level streaming progress. Next action is the owner's concrete recovery
step, not an inferred model plan. Existing historical tasks are populated as
reconciled; this is not an all-history backfill. Turn-owned foreground cards have
their existing TaskCard criteria and are outside these new background history
checkpoints. No claim is made that every requested product acceptance criterion
is complete.

## Final results

- Expanded command above against the reviewed implementation: **81 passed**, 71
  existing aiohttp/pytest warning instances, 50.19 seconds. Log:
  `/tmp/jaeger-baseline-20261108/durable-final-reviewed-tests.log`.
- Earlier strengthened race/child check (included in the final expanded run,
  with three additional dispatch-eligibility regressions):
  race/child tests including scheduler-tick settlement
  after an earlier attempt's child finishes: **9 passed**, 5.36 seconds.
- `git diff --check`: **PASS**. No bytecode/test caches found under the changed
  task implementation or core test directories.
- Overall durable acceptance: **PARTIAL**, for the evidence boundaries above;
  focused regressions and isolated subprocess recovery: **PASS**.

At handoff: implementation and bounded checks complete; no task-specific
blocker. Next action: independent review and repository-wide acceptance through
`scripts/verify.sh` by the coordinating task. Keep this branch isolated; do not
interpret these checks as authorization to deploy or replay uncertain work.
