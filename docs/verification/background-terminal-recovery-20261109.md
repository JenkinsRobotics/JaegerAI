# Qualified background terminal recovery

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
  child. Recursive child receipt qualification is not implemented.
- Cancellation is never turned into completion. Request cancellation revokes
  background projection durably, including across two restarts.
- Goal, tool, authority, objective generation, agent/session identity, native
  binding or authorization drift rejects proof without overwriting edited task
  state. No foreign-task alias or foreign bridge receipt is adopted.
- Artifact substitution, changed/missing checkpoints, altered effects and
  changed output/evidence snapshots reject recovery without tools/model replay.
- A retained seal is not a general transaction across databases. Gateway
  admission/seal/projection are transactional in Gateway SQLite. Native SQLite
  and files are independently fingerprinted and rechecked, not locked in one
  global transaction. No claim of protection from an arbitrary concurrent
  out-of-band writer, hardware durability guarantee, real provider outage,
  desktop behavior or general autonomous recovery is made.

## Verification

Evidence root: `/workspace/shared/bg-seal-test-state-20261109`.
All mutable HOME/cache/state/tmp paths are isolated under that root. Existing
`/tmp/jaeger-baseline-20261108/venv` is reused without installation. Explicit
`--basetemp` directories retain the final process fixtures.

- `baseline-reproduced.log`: unchanged base fails the new after-return process
  fixture with `execution_unknown != completed`, after all five synthetic
  native tools ran once. The separate baseline clone is
  `/workspace/shared/jaeger-background-seal-baseline-20261109`.
- `final-unit-regression.log`: 250 passed, covering new terminal journal tests,
  background admission tests and foreground journal regression tests.
- `domain-exclusivity.log`: one additional producer-domain exclusion passed.
- `final-new-unit.log`: all 57 new background journal tests passed after the
  final producer-domain guard; includes stale/missing projection lease checks.
- `final-verify.log`: complete `scripts/verify.sh` passed after the last
  production edit (hygiene, 294 IDE tests, frontend, Gateway, tiers, skills and
  HTTP/proxy wiring).
- `smoke-final.log`: 170 passed, 8618 deselected. The curated smoke files were
  inspected first; no denied browser/attached-client tests were retried.
- Final HTTP and verification-pipeline results are recorded alongside these
  logs. The HTTP fixtures script only provider/retrieval responses and the
  nominated crash barrier. Real HTTP admission, explicit approvals, native
  tools, SQLite effects, Research checks, SIGKILL and two full restarts run.
  They compare provider calls, tool events, native evidence and file bytes/mtime,
  and require one terminal event and one transcript delivery, with no replay.

Earlier diagnostic failures are retained: a hard-coded schema-version test;
an invalid pending-effect test API; a Research approval-name assertion; startup
checking native evidence before SQLite binding; and the Research verifier's
in-place result normalization. Each was corrected and specifically retested.
