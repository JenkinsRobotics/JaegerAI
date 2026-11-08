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

The schema-18 background journal is separate from foreground journals.
Schema 19 adds guarded owner-native enrollment, without historical backfill.
Before dispatch, the resident producer captures a single-use producer identity,
exact request identity, immutable task admission, admitted agent and Gateway
PID/generation. Only its normally awaited return may seal a clean, nonempty
completed result. The owner independently verifies artifacts or both Research
report/source-ledger obligations. Every accepted native run, checkpoint and
effect is checked and fingerprinted. After positive final verification, every
accepted root is legally completed and the files/operations/authority are
rechecked before the version-4 seal is written. No worker-supplied completed
status alone is sufficient. Binding another native after sealing is rejected.

Durable native runs legitimately remain active after yielded slices. Final
verified no-child results now legally complete the accepted roots before the
seal, so ordinary boot orphan recovery does not relabel already-proved work.
No recoverable/owner_lost label grants completion, and no illegal transition or
fake intermediate active state is used. Native completion alone still grants no
request recovery: loss after native completion but before seal stays unknown.

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

- Pre-seal process loss remains unknown, including the native-completion-to-seal
  gap. No interrupted replay is implemented.
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


## Completion-graph correction after the second hold

The first corrective freeze `a1ab122beb3cadfc0e8f40c8f1c4d79496a64501`
(tree `cea569ff713ad30e0bc73a91e3b346030e7c8ce8`) remains unchanged.
Its immutable `qualified-a1ab122` runner captured unit 318, full verify, smoke
170 and HTTP 12, each exit 0, plus runner exit 0 and unchanged source receipts.
Independent review nevertheless held it: five new adversarial failures covered
an indirect Gateway child native effect, truncating an earlier accepted-native
list, and incompatible native lifecycle after request projection. Three other
controls passed. A real schema17 upgrade probe produced by unchanged `ccda0c`
also exposed two pending-work false completions without any journal or replay;
its clean control passed. These failures are retained and are not superseded
by the passing original regression counts.

The next isolated checkout is
`/workspace/shared/jaeger-background-completion-graph-fix-20261109`, with evidence
under `/workspace/shared/bg-completion-graph-state-20261109`.
Schema 19 adds a single owner-written native enrollment record per request.
The guarded native binding transaction appends accepted IDs, including the
legitimate continuation pre-bind that occurs before the resident journal starts.
The record stores the exact request/admission identity and cannot be synthesized
from a shortened mutable task list. Source-side exclusivity consults this record
as well as retained legacy task ownership; even deleting a request does not
silently free an enrolled native for a foreign receiver. No upgrade backfills
historical task JSON as enrollment authority.

Version-3 seals require exact enrollment for every retained attempt. Missing or
inconsistent enrollment, request/admission identities or accepted root lineage
refuse completion proof. Bound same-task root reuse/rotation remains valid.
The ordinary completion veto follows qualified Gateway child request identities
into separately bound native roots, checks their recorded native identities and
native descendants, and refuses missing, pending or nonterminal work. A terminal
handoff label is not sufficient. This remains a negative safety check, never
recursive child seal/replay authority; any child still excludes a seal.

The negative veto also applies to identity-qualified background_admission_version
1 tasks with no journal. It can preserve ordinary clean retained completion or
pause known unresolved work, but creates neither journal nor enrollment records
and invokes no producer. Legacy tasks lacking that admission identity do not gain
recovery eligibility. Synthetic schema17/18 migration tests are in the repository;
the independent reviewer additionally regenerates actual ccda0c-produced inputs.

Accepted native waiting/blocked/failed states veto completion before task
publication. On a verified canonical background result, TaskOwner validates the
candidate outcome, performs the legal native completion transition, and only
then publishes the task completion. A transition failure pauses the task rather
than committing completed_verified and raising afterward. Gateway and native
stores still have no shared atomic transaction: a task-commit failure can leave
a legally completed native for later reconciliation, not require replay. The
previous cross-store and external-writer limitations remain explicit.

Preserved new diagnostics: `initial-tests.log/.exit` had 19 failed / 81 passed
(exit 1), revealing that a journal-only enrollment column missed legitimate
pre-dispatch binding. The guarded-binding record corrected that boundary;
`bind-tests.log/.exit` had 100 passed (exit 0). `graph-tests.log/.exit` had
115 passed (exit 0), covering the first graph tests. Later source-exclusivity
variants and pre-bind drift tests require final-frozen qualification; those
prior counts must not be presented as the final result. Final immutable runner
receipts and independent requalification determine whether this child can leave
HOLD. Neither preceding held checkout nor its evidence was modified.


## Producer completion and truthful Stop correction

Frozen `c7cbffab032d6de0655df3c038cb8bfc3b63d8e6` (tree
`8065a46d649bc7c63ce1c9332a579f505c1da113`) remains unchanged and held.
Its exact qualification passed unit 338, full verify and smoke 170, each exit 0;
HTTP was 2 failed / 10 passed, exit 1, and runner exit 1. The two positive
plain/Research recovery failures were real: request projection succeeded, then
RecoveryManager changed the orphan active native to recoverable/owner_lost and
the lifecycle veto paused TaskOwner. This was not an approval-state bypass or
a reason to trust a recovery label.

Independent c7 review had 60 unique passing completion/recovery/enrollment/
migration controls, then found four Stop failures plus one clean control. Stop
could report cancelled with an earlier accepted or indirect child native effect
pending, including truncated task history. Journal-independent ccda0c attribution
also had 2 failed / 1 passed, exit 1, proving this Stop defect was pre-existing.
Evidence is preserved at `/workspace/shared/bg-graph-review-state-20261109` and
`/workspace/shared/bg-attribution-state-20261109`.

The next isolated checkout is `/workspace/shared/jaeger-background-producer-settle-20261109`;
evidence root is `/workspace/shared/bg-producer-settle-state-20261109`.
Only after the exact awaited final result, artifact/Research verification,
current authority/lease and settled qualified graph are established does the
producer call legal native completion for every accepted root. It rechecks
files, operations and authority, then writes a version-4 seal with actual terminal
native evidence. Reads require that terminal evidence to remain exact. Earlier
seals are not silently upgraded. Yielded slices remain active. Roots that cannot
legally complete are refused rather than forced through an active state.

The completion graph also supplies a negative cancellation-settlement veto,
including in later cancellation reconciliation. Known pending effects, incomplete
enrollment/history, running producers or unresolved owned children keep a task
paused with cancellation retained; they do not produce a confirmed cancelled
outcome. Clean Stop and cancellation before admission remain supported. This
check does not mint a seal, invoke a producer, repeat effects or signal foreign
children. Retained enrollment is included even when mutable task history or a
request row disappears.

The process fixture now includes two distinct actually accepted native roots.
A synthetic executor legally closes its first returned partial slice; the real
TurnExecutive creates the next root through the normal binder. The final owner
still has to verify the full report. Tests require exact enrollment, terminal
states at the nominated barrier, every accepted checkpoint, stable native data,
provider/tool/effect/file counts, and once-only delivery across two real restarts.
The new native-settled barrier is before the journal commit: SIGKILL there must
leave completed native rows but an unknown request, with no replay.

Existing after-projection lifecycle fault tests use the legitimate ordinary
unsealed completed-child path, where an active root can still legally move to
waiting/failed/blocked. Equivalent faults before the producer seal are also
covered. For a sealed final result, native completion is already terminal and
such a later transition is rejected by the native state machine; the tests do
not force an illegal transition merely to preserve an old active-root premise.

Pre-freeze diagnostics are retained with explicit exits:
- `initial-tests`: 120 passed, exit 0 before the additional boundary cases.
- `boundary-tests`: 136 passed, exit 0, including truthful Stop and drift during
  native-completion-to-seal verification.
- `boundary-http`: 3 passed / 2 failed, exit 1. Plain/Research sealed recovery and
  native-completed-without-seal preservation passed. The rotation fixture used
  the wrong session namespace, so its two rotation cases never reached the
  nominated barrier; these are fixture failures, not passing qualification.
- `rotated-http`: the corrected two rotation cases passed, exit 0. Assertions
  were strengthened to require two distinct enrolled roots, all their native
  checkpoints and exact expected states, not relaxed to a one-root path.

Final-frozen tests and independent review remain separate evidence. The final
HTTP suite contains ten background terminal cases plus five affected existing
cases. No check here claims general interruption replay, provider outage
recovery, Mac/runtime/browser qualification, or an atomic cross-store commit.
