# Durable outcome and recovery repair, 2026-11-08

Fourth isolated increment, after `4cb679c2494799d58b43414926419e07fe8df47e`.
The same dedicated branch and all three earlier commits are preserved. No merge,
runtime-Mac edit/build/restart, external provider execution or remote write.

## Confirmed defect

The durable owner verified the presence/freshness of an artifact before respecting
the worker's outcome. A fresh but unfinished report plus a canonical completed
request with `halt_reason=yielded` became `completed_verified`, was delivered to
the parent, and never continued. Blocked, needs-owner and error outcomes had the
same precedence problem. A completed request means that one execution slice
ended, not that the whole objective succeeded.

The first regression matrix plus killed-process case produced **6 failures and
4 passing controls** against the preceding implementation. The bounded initial
repair passed 52 expanded checks, but independent review found an important gap:
the real continuation controller preserves loop-breaker halt markers without
necessarily setting a separate error field. Context overflow, stalled execution,
empty response and other explicit halts could still falsely complete a partial
artifact. Seven real-controller regressions failed against that initial guard.

## Final producer change

Only `jaeger_ai/core/tasks/owner.py` production code changes in this increment.
Its settlement path now:

- Allows artifact verification only for a completed request, no error, and an
  absent/None/empty halt marker, preserving the established legacy success shape.
- Keeps cancellation and unknown-outcome handling first. Unknown effects stay
  paused and are not re-approved or replayed.
- Continues an explicit yielded checkpoint without consuming a failure retry.
- Retains blocked and needs-owner outcomes instead of replacing them with success.
- Retains other explicit halts as failure, without resetting counters or starting
  another attempt. Restarting a loop-breaker could repeat failed effects.

Actual inner budget boundaries are tested through `run_continued_turn`: they
normalize to the existing yielded contract and still continue. No new scheduler,
retry policy, permissions, completion protocol or model dependency is introduced.
Existing successful file evidence is still re-read and hashed. That verifies
identity/freshness, not semantic quality of arbitrary generated content.

## Verification

New `test_task_outcome_precedence.py` contains **23 regression/control cases**.
It covers legacy clean completion, outcome precedence, retained checkpoints,
actual controller loop-breakers and budget normalization, and an abrupt-process
recovery case. The process case exits using `os._exit` with the database lease
held after saving a yielded receipt. Three successor processes reconcile, finish
one continuation, and reconcile again. Assertions establish:

- No premature delivered result after the partial slice.
- One new continuation request/effect, not replay of the completed first slice.
- The saved checkpoint reaches that continuation.
- No failed-retry budget is consumed by yielding.
- One final delivery; the later restart repeats neither effects nor messages.

Expanded focused suite: **65 passed**, 20 existing aiohttp warning instances,
44.09 seconds. With an external HOME/state/cache and the documented venv:

```sh
python -m pytest -q \
  dev/tests/jaeger_ai/core/test_task_outcome_precedence.py \
  dev/tests/jaeger_ai/core/test_gateway_task_owner.py \
  dev/tests/jaeger_ai/core/test_task_execution_races.py \
  dev/tests/jaeger_ai/core/test_task_child_cancellation.py \
  dev/tests/jaeger_ai/core/test_task_owner_process_recovery.py \
  dev/tests/jaeger_ai/core/test_durable_tasks.py \
  --basetemp=/tmp/jaeger-baseline-20261108/execution-audit/pytest-strengthened \
  -o cache_dir=/tmp/jaeger-baseline-20261108/execution-audit/cache
```

Evidence under `/tmp/jaeger-baseline-20261108/execution-audit/`:
`final-fail-before.log` (first six failures), `loop-before.log` (seven additional
loop-breaker failures), `strengthened-pass.log`, `strengthened-owner.diff` and
`strengthened-test.diff`. Earlier `final-pass-after.log` is the superseded
52-test initial guard, not the final qualified implementation.

Independent review accepted the strengthened source, exact clean-completion
contract and process test after its findings were fixed. The reviewer inspected
the final logs and diff; it did not rerun every aggregate. It also checked that
canonical `task_completion` is only installed after successful ledger verification,
not a negative result hidden behind an empty halt marker.

## Integrated qualification

Counts overlap and are not a unique-test total.

- Expanded durable/recovery aggregate: **PASS, 104 tests**, 66.42 seconds, using
  the [earlier durable command](durable-task-acceptance-20261108.md) plus the new
  outcome-precedence file.
- Security tier rerun: **PASS, 203 tests, 2 skipped**, 12.29 seconds.
- Full UI879 / 200 files and the production UI build remain the unchanged,
  previously tested third-increment assets. No UI source or lockfile changed.
- Final repository `scripts/verify.sh`: **PASS, 430 tests** across its documented
  tiers. Production-path rerun: **PASS, 75 tests**, 19.25 seconds.
- Root wheel and source archive rebuilt from the final owner source: **PASS**.
  Eight unchanged companion-package archives from the third increment were
  retained byte-for-byte; all ten passed archive inspection. Both new root
  archives independently match the final owner source and no-mock UI fingerprint.
  No package was installed or deployed.
- Changed-Python critical lint and whitespace: **PASS**.
- Existing full owned HTTP/process diagnostic: **1 failed, 33 passed,
  3 deselected**. The failure exposed a previously false-positive test fixture,
  described below. Corrected focused real HTTP/restart journey: **PASS, 1 test**,
  17.39 seconds. Full combined HTTP qualification is deferred to the following
  foreground-outcome increment, not falsely reported green here.
- The core aggregate gates preceded the fixture-only refinement. No production
  code changed during that refinement; the final focused journey tests it.

The retained production UI fingerprint is
`f6e4f00489d65292d6c25d21deafe2a77332c8708939c23f288e1bf8bfbd139c`,
`mock=false`. Build output remains `/tmp/jaeger-baseline-20261108/ui-third/dist`.

Overall product and per-tab acceptance remain **PARTIAL**. These tests use real
SQLite and independent processes with synthetic local workers, not a configured
provider/native-host crash. Browser/phone, media/voice and external account
workflows remain unqualified. The headless package-suite and IPC limitations
recorded in the [third report](assistant-core-authority-streaming-20261108.md)
remain. No remote branch, PR or CI exists because write access is still blocked;
no denied write was retried. Runtime-local work remains untouched and must be
reconciled separately before any deployment the user later approves.

Final aggregate logs under `/tmp/jaeger-baseline-20261108/`:
`verify-fourth-final.log`, `production-fourth-final.log`, `durable-fourth.log`,
`security-fourth.log`, `http-fourth-final.log`, `packages-fourth.log` and
`artifacts-fourth.log`.

## Existing happy-path fixture correction

The full owned HTTP suite exposed a false-positive earlier test, not a reason to
relax the new completion guard. `CONTRACT-DURABLE` in the scripted provider called
`complete_task` with `{}`. That real tool requires evidence and returned `ok=false`.
Saved receipts showed `task_completion=null`, `halt_reason=yielded`, and a failed
complete_task event. The old file-presence bug had hidden this unfinished work.
The diagnostic runs are retained in `http-fourth.log` and `http-fourth-final.log`;
these are not successful final-source runs.

The fixture now calls the real write and read tools, checks the actual readback
content, and supplies evidence and summary to the real completion tool. The HTTP
test additionally requires attempt zero, successful canonical task_completion,
an independently checked file SHA-256, no halt and no failed completion-tool
event. Restart still delivers once and makes no more provider calls. No receipt
is fabricated and no production completion assertion is bypassed.

Final focused result: **1 passed**, 17.39 seconds, in
`execution-audit/http-fixture-final.log`. Fixture/test changes are in
`dev/tests/fixtures/gateway_contract_worker.py` and the existing
`test_gateway_owned_process_contract.py` durable journey. Independent review
checked the corrected tool sequence and receipt assertions. This supersedes the
older journey's completion evidence, which had been masked by the production bug.

A separate foreground audit has reproduced halted Chat turns showing success.
That next bounded producer repair is kept separate from this committed durable
increment. No overall product completion or foreground automatic-resume claim is
made here.
