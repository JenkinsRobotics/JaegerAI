# Resident receipt routing qualification, 2026-11-08

## Scope and result

Resident request recovery now refuses proof from the unrelated native bridge
receipt store. A resident binding returns `owner_request_receipt_unavailable`,
`source=resident_owner`, and `execution_unknown=true`. It neither opens the
bridge store nor replays work. Existing bridge recovery remains supported.
This is a conservative routing fix, **not full resident terminal recovery**.

The actual owner producer uses `OWNER_RUN_SESSION_PREFIX = "owner:"` in
`JaegerGatewayApp._owner_react_turn`. Tests use that constant, not an invented
`owner-run:` prefix. The latter appeared in the initial external audit and did
not reflect the production binding.

## Producer limit

`EntityRuntime.run_subordinate_react` runs `TurnExecutive` with `SqliteRunStore`.
An inner completed checkpoint does not qualify the admitted request:
`_continued_owner_react` can execute more steps and corrections, durable tasks
can leave the run active, and Gateway still must classify owner decisions,
settle task cards, and check cancellation. RecoveryManager's recoverable or
blocked states do not prove terminal completion either. An empty effect ledger
alone cannot prove that the whole request finished.

The existing authoritative full-request commit is `complete_request`, called
from Gateway finalization. It atomically persists result, transcript, and event.
Adding a second receipt beside that commit would require an explicit producer
ownership/fencing and cancellation protocol, not simply adapting inner run
status. This patch deliberately leaves crashes before that commit unknown.
It adds no schema, executor, scheduler, replay, or inferred success path.

## Tests

`test_resident_receipt_routing.py` uses actual `TurnExecutive`, SQLite run and
commitment stores, a scripted local agent loop, native checkpoint writes,
Gateway store reopening and interrupted-session recovery, and `handle_reconcile`.
No provider call or resident terminal-row fabrication is used.

- Actual inner states completed, cancelled, and active all remain unknown at
  the request boundary when no owner request receipt exists.
- Genuine bridge accept/finish receipts with coincident IDs cannot attest a
  resident result. Before the fix, all three variants incorrectly returned 200.
- Unknown outcomes do not append assistant output or promote queued work.
- Explicit unknown acknowledgment keeps no-replay/no-promotion semantics.
- The owner route does not even resolve the bridge storage root.
- Genuine bridge receipt behavior and missing bindings remain unchanged.

Fail-before: 7 failed, 1 passed. After: 52 passed for the new suite plus existing
queue reconciliation suite. Existing recovery/cancellation suites are separately
qualified in the accompanying execution report. No live runtime, network provider,
HTTP server, deployment, or upstream write is involved.

## Integrated qualification and retained failure

The focused producer tests above use no HTTP server. The merged candidate also
ran the existing owned HTTP/process suite with the scripted provider boundary.
That broader run is **PARTIAL: 42 passed, one failed, three established browser/
IPC exclusions**. `test_gateway_cron_fire_is_one_durable_turn` failed to produce
its expected assistant response. The preserved child log identifies a real
`CommitmentError: cannot move ... from active to active` during `ensure_run`,
not a provider response that merely arrived after the assertion. A concurrent
host-sensor initiative and scheduled turn competed to activate the same newly
created turn-loop commitment. The routing guard did not alter that producer;
its aggregate qualification is nevertheless not reported as green. A separate
bounded producer repair and deterministic concurrency regression are required.
The assertion and deadline were not weakened, and the failed log/database were
preserved. The previous tenth-increment HTTP run passed 43 tests, which does not
invalidate this later failure.

Other final checks against this merged guard source passed:

- Repository verification: 430 tests.
- Production-path: 75 tests; security: 203 tests with two skips.
- Durable/recovery aggregate including the new routing suite: 327 tests.
- Independent receipt-boundary review: 66 tests (60 existing/focused controls
  and six additional collision/boundary controls).
- Root wheel and source archive rebuilt with the previously qualified UI;
  eight unchanged companion archives retained and all ten inspected. Changed
  runtime bytes matched source and the no-mock UI fingerprint matched
  `36612489016ec2283f86dcc22d435be6aa80478591ab9dcb4551833c7be0fc1f`.
- Critical lint and whitespace checks passed. The unchanged UI's preceding full
  qualification remains 910 tests across 201 files, TypeScript, theme and build.

These are overlapping scopes, not a sum. Reproduction uses the same isolated
HOME, state root, external caches and scripted provider fixture described in
[the test environment](assistant-core-test-environment-20261108.txt). Exact final
commands, logs and source hashes accompany the review artifact. The owned HTTP
profile disables optional skill smoke subprocesses; it does not qualify cold
production skill initialization or non-core missing-smoke gates. No browser,
phone, native host, real configured provider or installed-runtime acceptance is
claimed. All product/tab acceptance remains PARTIAL. Whole-request resident
journal work is separate and is not part of this guard increment.
