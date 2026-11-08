# Request-qualified resident journal, 2026-11-08

## Scope

This increment extends the separately verified resident/bridge receipt-domain
guard. It does not infer request completion from an inner run, model text, an
empty effect list, or a bridge receipt. No executor, scheduler, or replay path
is added. One additive table in the existing Gateway SQLite database records
producer ownership, all accepted native run IDs, and a sealed request outcome.

Qualifying scope is the canonical unassigned resident foreground owner path with a current
Gateway process lease and matching digest-v2 admission execution snapshot.
Caller/tool grants remain in the existing scopes. Initial attachments, explicit
options/background work, subordinate/specialist paths, CLI/framework selectors,
legacy requests and existing durable background tasks do not acquire recovery
proof. Yield/blocked/needs-owner outcomes remain unsupported for sealed recovery.
A foreground TaskCard may qualify only after the existing verifier/state machine
settles it to completed_verified, failed, or a qualified normally returned cancelled outcome. Request status and task status retain
their existing distinct meanings and both are retained in the snapshot.

## Producer and authority boundary

1. Begin a journal before any resident run dispatch. Capture immutable request,
   session, turn, digest/version, admitted execution, input and creation identity;
   capture the Gateway lease PID/start epoch and a private producer token.
2. Before each on_run callback can dispatch effects, validate its live native run
   ownership and token/lease/request identity; append its ID and bind it atomically.
   Completed inner runs may rotate, so the latest native_run_id is insufficient.
   Both directions of run-ID theft between journal and legacy owner bindings are
   refused. Bridge receipt identity remains a separate domain.
3. After the entire awaited continuation returns, check every accepted run and
   its effect ledger before memory, successful card or result settlement. Missing
   run ownership, pending/unreadable effects, or a producer conflict fail closed.
4. Recheck at finalization. Foreground TaskCard verification/state update, its
   durable task.updated event and immutable request snapshot share one SQLite
   transaction. The existing task owner and task store accept the transaction;
   they do not use a second coordinator. Rollback discards both rows and queued
   event fanout, including BaseException interruption.
5. Normal projection and reconciliation consume the same immutable full result,
   assistant text, session status and follow-ups through complete_request. Its
   existing result/transcript/event transaction and historical-session guard
   preserve idempotence and newer session ownership. Conflicting projection or
   a storage KeyError cannot take the legacy success fallback.

There is no receipt production from an asynchronously cancelled await or a worker
exception. Before an accepted run, cancellation can still truthfully be cancelled.
After acceptance, uncertainty stays unknown and late callbacks cannot reopen it.
No approval, model request or effect is replayed.

## Crash and failure behavior

- Before a sealed snapshot: restart stays unknown. Inner completed/cancelled/active
  checkpoints are not substituted for request proof.
- During atomic card/snapshot finalization: failure rolls back successful card
  state, its event and proof together. Normal error handling pauses the card and
  records unknown. A process-loss simulation may leave an unfinalized card, but
  never a durable verified card from the rolled-back transaction.
- After sealing but before terminal projection: the verified card and immutable
  result survive. Explicit reconciliation, or the existing startup recovery hook,
  projects once without another model/tool execution.
- The startup hook runs immediately after lease acquisition and interrupted-state
  marking, validates each sealed row and its current recovery lease in the
  projection transaction, and leaves invalid/unsealed/legacy cases alone. It does
  not dispatch queues; the existing end-of-startup drain retains that ownership.
- Live projection failure attempts a guarded pending-projection marker. Its text
  distinguishes a committed result awaiting projection from unknown effects;
  it preserves the proof and newer sessions. If storage cannot write even this
  marker, the failure is logged; marker success is not assumed.

## Qualification

The tests execute the real Gateway request/continuation/finalization path,
TurnExecutive, SQLite runs/effects/checkpoints, work ledger, TaskCard verifier,
lease, request store, restart projection and reconciliation. Only the model/runtime
port is scripted. A dedicated case uses the real _open_turn_card path and actual
complete_task file-verification receipt; its inner durable run remains active
while the request is safely sealed, proving inner status is not the adapter.

Tests cover migration without backfill; admission authority/digest/source drift;
lease/token and cross-request run collisions; all accepted continuation effects;
queue/card/message/event outward truth; no-run cancellation and empty/no-tool
completion; late callbacks; asynchronous cancellation; immutable proof and
conflicting projection; duplicate recovery; controlled pre/post-snapshot crashes;
atomic card rollback with live-event checks; postcommit display failures;
foreign-card cleanup; mixed sealed/unsealed startup and newer session ownership.

The identical independent crash contract fails on the frozen guard with HTTP
409/execution_unknown and passes on the journal candidate with HTTP 200/completed.
Both execute the model port exactly once. This is a request-producer comparison,
not a fabricated terminal-row test.

The initial producer tests are isolated and in-process. Later owned HTTP and
combined qualification are recorded below; they do not use a real provider, live
runtime state, deployment or upstream write. The initial worker excluded the
command-session process case from its focused run; the broader parent gates are
separately identified rather than counting that exclusion as a pass.

## Existing foreground transfer compatibility

A yielded foreground request has no sealed journal outcome. Its existing
GatewayTaskOwner can still transfer that run to its durable child using the
retained continuation-admission contract. The internal native-binding callable
reuses the existing admission/continuation validators inside the binding
transaction; options or a raw task ID alone grant nothing. It validates source
journal identity/domain/last accepted run, normal completed-yielded projection,
child session/input/authority/attempt/native ownership, and current task/child
cancellation. This exception never applies to a sealed source. A transferred
source cannot later be sealed because its request is already terminal.

Sequential real foreground tasks have distinct native ownership. An earlier
sealed outcome is not reclassified from a later request's effects. Late unknown
child callbacks stay unknown instead of being downgraded to failed and releasing
their queue. Unknown cancellation likewise cannot certify prior uncertain work.

Pending live projection markers use the captured Gateway lease and emit one
transactional turn.unknown event with committed-result-pending text. Repeated
failure does not duplicate the marker event. This is a projection-pending state,
not a new assertion that already-sealed effects became uncertain.

## Returned cancellation correction caught by integration

The full owned-process gate exposed a real bridge cancellation regression:
all journal-bound cancellation had conservatively been projected unknown, even
when the whole awaited continuation returned after the provider interrupt.
Only that normal-return branch now qualifies cancelled proof, using the same
producer token, current lease, immutable identity, current native binding and
all accepted-run effect checks. Async await cancellation and raised worker
exceptions remain unknown after native acceptance. Interrupt delivery alone is
never proof of quiescence.

A resumable foreground card is paused and marked cancellation-requested by the
existing cancel API. Atomic returned-cancellation settlement may close that
card only after the same proof checks, with no unconfirmed owned descendants.
The shared TaskCard mutation requires an active transaction and CANCELLED state;
any failure to reach that state rolls back instead of projecting a cancelled
request with an unsettled card. Duplicate cancel/reconcile cannot change the
immutable sealed outcome. Unknown results do not emit confirmed cancellation
or drain the queue.

Actual entry-path limit: ordinary UI native:jaeger home/new chat resolves a
registry lead role. The original journal eligibility requires no role, so that
path remains excluded in this increment. The qualifying bridge request is an
unassigned canonical resident foreground. Direct HTTP tests using role lead
remain valid existing cancellation controls but do not prove journal recovery.
Default lead qualification is separate work; this correction does not widen
journal authority or claim general UI recovery.


## Final combined qualification

The original combined journal run retained a genuine failure: 42 owned HTTP
checks passed and the existing bridge-cancellation check failed. Independent
actual cancellation-API tests then caught two further card-state gaps: rejecting
the existing cancellation-requested marker, and silently leaving the card paused
while projecting the request cancelled. These were repaired at the producer and
transactional TaskCard mutation boundaries, not by weakening assertions.

Against the final corrected runtime source:

- Repository verification: 430 tests, PASS.
- Production-path: 75 tests, PASS (21.42 seconds).
- Security: 203 tests, two skips (18.18 seconds); skips are not passes.
- Durable/recovery: 402 tests, PASS (126.79 seconds).
- Agent runtime/commitments: 120 tests, PASS (6.27 seconds).
- Owned HTTP/process: 43 tests, PASS, three established browser/IPC exclusions
  (592.40 seconds). Both cron/initiative activation and bridge cancellation pass
  with the existing assertions/deadlines. The previous failed runs remain saved.
- Corrected frozen independent journal review: 86 tests, PASS (75 journal plus
  11 external controls). Separate focused producer and targeted HTTP runs overlap
  these scopes and are not added to the totals.
- Root and jaeger-agent wheel/source archives rebuilt; six unchanged companions
  retained; all ten inspected. Eight root and five agent runtime module contents
  match source; the no-mock UI fingerprint matches
  36612489016ec2283f86dcc22d435be6aa80478591ab9dcb4551833c7be0fc1f.
- Critical lint and whitespace PASS. UI code did not change: the preceding
  910-test/201-file build qualification was reused after independently verifying
  its 866-file source snapshot still matches the main UI.

Exact runners, frozen source hashes, initial failures and final logs accompany
the cumulative review artifact. All test state, caches and package staging stay
outside the source tree. Cold optional skill smoke subprocesses remain disabled
only in the synthetic HTTP fixture; production defaults remain unchanged.

The current default branch was rechecked read-only at
ff71bb769bc56e4c6d7be6d540a86be73e291e07. No remote write, merge, installation,
Mac runtime build/change/restart or deployment was performed.

## Remaining acceptance and separate work

Overall and per-tab acceptance remain PARTIAL. Ordinary named native:jaeger UI
lead chats still lack this journal qualification; a separate fresh-admission
identity repair is being tested. A separate complete create-handler regression
also confirmed that top-level selected agent_id is ignored and archive_on_create
substitutes the lead. Selecting a different agent in a new chat therefore still
needs the separate session-creation repair; default lead behavior is unchanged.
Neither pending repair is included in this increment.

The new seal/projection crash boundary has producer-level crash simulation, not
an actual SIGKILL/restart qualification. Prepared but unexecuted process-loss
tests are not counted. Browser reload/phone/native host, actual configured
providers, voice/media and external accounts remain unqualified. Historical,
unsealed, asynchronously unreturned, indeterminate-effect and unsupported paths
remain conservative; no automatic replay is introduced.

## Later chat-selection increment

The separate [chat-agent selection repair](assistant-core-chat-agent-selection-20261108.md)
now preserves the explicitly selected agent during creation and existing history
on retries. Its scoped qualification does not imply named-lead journal recovery,
which remains separate. The historical missing-selection finding above describes
this thirteen-commit snapshot, not the later repair.
