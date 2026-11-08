# Background terminal recovery boundary

Base: `ccda0c799445ab1480817eb0f7bac99e1c2f6704` (tree
`0f37ec3c2564028b65f7d0668fca470cdf8d4cb9`). Local isolated implementation only.
No Mac runtime, upstream fetch, GitHub write, deployment, installation, browser,
AF_UNIX test, credential or existing packaging artifact changes.

## Defect and bounded repair

A newly admitted default/native-lead background task previously retained its
execution contract, checkpoints and effects, but no owner terminal journal.
Killing the owned Gateway after the final returned result and before request
projection left the request `execution_unknown`, even with complete report
bytes. The new process fixture reproduces that failure on the unchanged base
with only the test fixture and test copied into a separate clone.

The additive schema-18 background journal is separate from foreground journals.
Before dispatch, the resident producer captures a single-use producer identity,
exact request identity, immutable task admission, admitted agent and Gateway
PID/generation. Only its normally awaited return may seal a clean, nonempty
completed result. The owner independently verifies artifacts or both Research
report/source-ledger obligations. Every accepted native run, checkpoint and
effect is checked and fingerprinted. No worker-supplied completed status alone
is sufficient. Binding another native after sealing is rejected.

Durable native runs legitimately remain active until TaskOwner settlement,
including after a clean final slice. Recovery does not invent a terminal native
state. Returned producer identity plus positive independent verification is the
completion proof; an active checkpoint or absence of pending effects is not.

Normal projection and recovery both use the exact sealed output. Research
verification intentionally replaces provisional worker prose with the checked
report bytes. The journal verifies a copy, seals those owner bytes, and the
normal producer reads that seal before writing the transcript. Recovery does
not choose a different answer. TaskOwner subsequently follows its existing
receipt reconciliation and independent verification path.

Startup preserves early foreground recovery. Background proof is checked after
binding the existing native SQLite instance, before runtime producers and task
scheduling. Normal, startup and explicit-reconcile background projection require
the current Gateway PID/generation. The canonical result, assistant message and
terminal event use the existing atomic/idempotent request projection.

## Negative boundary

- Pre-seal process loss remains unknown. No interrupted replay is implemented.
- Historical tasks, explicit-provider/specialist routes and foreground journals
  do not acquire this recovery contract.
- Yielded, blocked, owner-needed, failed, empty and unverifiable returned results
  remain unsealed. Legitimate live multi-slice continuation is retained.
- Any delegated child relationship excludes recovery in this slice, including
  a child attached only to an earlier accepted native run or a terminal-labeled
  child. The corrected version includes native parent/root descendants and all
  earlier retained admissions, not only Gateway handoffs on the current attempt.
  Recursive child receipt qualification is not implemented.
- Cancellation is never turned into completion. Request cancellation revokes
  background projection durably, including across two restarts.
- Goal, tool, authority, objective generation, agent/session identity, native
  binding or authorization drift rejects proof without overwriting edited task
  state. No foreign-task alias or foreign bridge receipt is adopted.
- Artifact substitution, changed/missing checkpoints, altered effects and
  changed output/evidence snapshots reject recovery without tools/model replay.
- Changed live default-route/tier settings can leave a recovered request
  completed while TaskOwner pauses at its stricter current dispatch guard. This
  is a conservative reconciliation limitation, not permission to replay work
  or bypass that guard.
- A retained seal is not a general transaction across databases. Gateway
  admission/seal/projection are transactional in Gateway SQLite. Native SQLite
  and files are independently fingerprinted and rechecked, not locked in one
  global transaction. No claim of protection from an arbitrary concurrent
  out-of-band writer, hardware durability guarantee, real provider outage,
  desktop behavior or general autonomous recovery is made.

## Original candidate verification and independent hold

Original candidate: `ec8353cde1bde2e1ca131acb33a1d0a697086d78`, tree
`079c66213de5e9be2a78cef8b57251e0793b0c62`. Its checkout and evidence remain
unchanged. Evidence root: `/workspace/shared/bg-seal-test-state-20261109`.
Existing `/tmp/jaeger-baseline-20261108/venv` was reused without installation.
Runner HOME/cache/TMPDIR and explicit basetemps are isolated under that root,
but inherited `dev/tests/conftest.py` also creates disposable synthetic
`/tmp/jaeger-tests-*` state/caller tokens explicitly. These are not user state;
TMPDIR does not redirect that fixture. Do not claim every path was under the
shared evidence root.

- `baseline-reproduced.log`: unchanged base fails the new after-return process
  fixture with `execution_unknown != completed` after all five synthetic tools.
  Baseline clone: `/workspace/shared/jaeger-background-seal-baseline-20261109`.
- `final-unit-regression.log`: 250 passed on the draft before the last producer
  domain guard. This is not final-frozen source qualification.
- `final-http-regression.log`: diagnostic summary 12 passed. Its trailing-tail
  wrapper did not capture the pytest exit code; do not credit wrapper exit 0.
- `qualified-ec8353c/status.tsv`: explicit unit exit 0 (251 passed), complete
  `scripts/verify.sh` exit 0, smoke exit 0 (170 passed, 8623 deselected).
- `qualified-ec8353c/http.exit`: explicit exit 0, 7 new process cases passed.
- `qualified-ec8353c/http-regression.exit`: explicit exit 0, 5 affected existing
  process cases passed. The two HTTP invocations cover all 12 without repeating
  them within the final explicit-exit qualification.
- All final runners preserve source-before/source-after identities and clean
  worktree receipts. No denied browser/attached-client nodes were retried.

Those passing tests did not establish the no-delegated-tree boundary.
Independent review placed ec8353c on HOLD: final selected held-out run had
7 failed / 22 passed, explicit exit 1. The native child ledger was not consulted,
and earlier attempts' rotated natives were omitted from handoff/effect/evidence
qualification. Both pending-child and pending-prior-native cases could falsely
complete the task and gain a terminal seal. Frozen independent raw failure log:
`test-evidence/seal-review-evidence__frozen-final.log`.

A separate journal-independent attribution probe against unchanged `ccda0c`
had 2 failed / 2 passed, explicit exit 1: ordinary pending-child/prior-native
false completion predates the journal; sealing/recovery over those unresolved
outcomes was introduced by ec8353c. Clean and completed-child controls passed.
Attribution evidence: `/workspace/shared/bg-attribution-state-20261109`.

## Corrective increment

Correction checkout: `/workspace/shared/jaeger-background-native-child-fix-20261109`.
Evidence: `/workspace/shared/bg-child-fix-state-20261109`.
No source or evidence in the held original checkout was changed.

The version-2 seal snapshots every retained background admission and its full
deduplicated native run trajectory separately from the current request's own
native run IDs. Every earlier attempt's request/turn/native reference contributes
to child exclusion. Native parent and root links are checked across the ledger,
including root descendants whose immediate parent is outside the accepted set.
Accepted root reuse/rotation remains supported; foreign lineage, delegated
accepted runs and cycles cannot acquire this seal. Prior-run effects and
checkpoints are fingerprinted and rechecked at seal/projection. Version-1 seals
are not retroactively promoted to the stronger completion contract.

For enrolled background producers, unresolved native descendants, pending
operations or unavailable accepted evidence veto both sealing and normal task
settlement. TaskOwner repeats that veto in its task-write transaction after
artifact verification, so a late pending operation cannot be hidden behind a
completed request. A fully settled child tree is still unsupported for journal
recovery but may finish through existing ordinary artifact verification. No
terminal child label is adopted as recursive recovery authority.

Pre-freeze explicit diagnostics: `initial-tests.log/.exit` (91 passed, exit 0)
preceded the normal-settlement guard; `settlement-tests.log/.exit` (95 passed,
exit 0) covers the guard, pending/active descendants, settled child control,
all-attempt scope and late request-to-task settlement changes. Additional
accepted-root lineage cases are included in the corrective test file. Final
frozen qualification is recorded under this correction's evidence root with
immutable commands, source identities and explicit shell exit receipts. It must
be reviewed on that exact source before integration; earlier passes are not a
substitute for those results or for independent review.

The real HTTP cases script only provider/retrieval responses and nominated
crash barriers. HTTP admission, explicit approvals, native tools, SQLite effects,
Research checks, SIGKILL and two full restarts are real. They compare provider
calls, tool events, native evidence, file bytes/mtime and once-only terminal
projection; they are not real-provider, browser or Mac qualification.

All earlier diagnostic failures remain retained: hard-coded schema test,
invalid pending-effect API, Research approval assertion, pre-binding native
recovery, in-place Research normalization, and independent held-out failures.
The cross-store fingerprint limitation above remains unchanged.
