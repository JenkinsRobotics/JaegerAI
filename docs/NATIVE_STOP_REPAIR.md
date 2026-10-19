# Stop repair — containment, frontend, backend

Stop/cancellation is first priority. Tasks/Kanban client integration remains paused.

## Live containment evidence (existing installed source, not this patch)

One running native Jaeger session was found through GatewayTurnClient using the existing menubar caller, with credentials handled by that client and never printed:

- session `agent-native:jaeger`
- request `d5c754fd-928f-412c-9e81-89c1b998001f`
- owner run `61d3de04855f4052`
- one POST cancellation accepted; interrupt_delivered=true, cancellation_confirmed=false
- cancel event 944908 at Unix 1792423750.880736
- final tool start before cancel: `mcp__rea__analyze_javascript_application`, event 944907
- subsequent tool.failed 944909, turn.unknown 944912
- request updated_at=1792424063.428282; checked 2026-10-19T15:37:34.710912+00:00
- request and session both `execution_unknown`; result says cancelled with an external effect whose outcome is unknown; reconcile

The agent request has settled unknown. This is not a confirmed stop of the remote REA operation. No child PID/request handle sufficient for a separately scoped remote cancellation was exposed. No service restart, shared MCP disconnect, broad kill, unrelated cancellation or live new task was performed. The scoped POST /v1/sessions/{id}/reconcile exists but requires a conclusive native receipt; it is not force-cancel. Unknown effect records must not be fabricated away to unlock admission.

## Frontend changes

- GatewaySessions: require exact request_id on cancellation; decode authoritative request state and distinguish cancelling/cancelled/execution_unknown. Unknown is a terminal stream event, not success.
- ChatViewModel: read latest admitted request from the selected session independently of local isSending; use exact session/request identity for Stop; preserve an uncertain-stop latch so refresh does not cause resend; pause local queue draining while retaining queued text; preserve partial answer text after interrupted/error settlement.
- ChatView, ChatComposerView, ChatPresentation: expose Stop for recovered/external active turns and show truthful state. Status remains visible on connection failure or unknown settlement. A legacy Gateway without the control field disables scoped Stop with an update explanation.
- BridgeProcess: generate/pass turn_id and scope menu/pill cancellation to that in-flight turn; never emit a blanket cancel when no local turn is tracked.
- AgentBridge: do not relabel cancellation/unknown errors as a model stall encouraging resend.
- AmbientLoop: retain submission/accepted request identity for voice cancellation, defer the single cancel when barge-in races admission, surface unconfirmed cancellation, and recognize unknown stream settlement.

No partial transcript is deleted to indicate Stop; unrelated sessions and their queues are untouched.

## Backend changes

- Gateway GET /v1/sessions/{id}: add a small latest_request control projection (identity/state/timestamps only), excluding queued/paused follow-ups by reusing the store's existing latest_request query. Optional ?view=control omits transcript and chrome fields from the response for native polling. Existing authentication and session confinement remain in force. No new execution/cancel authority, provider or model setting.
- MCP client: observe the current turn's cancellation while waiting for this call's future. Cancel that future, leaving the shared transport and other futures intact. Timeouts also cancel their own future. Remove automatic second invocation after exceptions: an external effect may have happened. Report the remote outcome as unconfirmed; the existing effect ledger keeps the claim pending on raised errors, so Gateway can settle execution_unknown honestly.

This does not promise a remote MCP server honors cancellation. Existing scoped SDK cancellation is best effort; no transport-wide teardown was added.

## Minimal checks and integration limits

- Swift build: external /tmp/jaeger-native-panels-build.
- StopControlTests: exact cancellation body/nonempty identity, recovered request state versus cancelling/unknown/cancelled, partial reply preservation.
- dev/tests/jaeger_ai/core/test_stop_recovery.py: isolated Gateway projection preserves queued follow-up; blocked MCP fake is interrupted without retry while an unrelated future completes; timed-out MCP fake is cancelled without replay.
- git diff --check.

No broad monorepo suite, paid model call, live validation task, installed app replacement or restart. This is source repair; installed Stop is not fixed until reviewed/deployed and verified. The separate uncommitted WebUI native-context draft from the paused panels work is excluded from the Stop commit.

## Remaining ordered work

1. Review/integrate this Stop patch and establish installed-client acceptance; reconcile the existing REA effect from a conclusive receipt without replay.
2. Resume authenticated WebUI native session/profile contract review (draft remains separate).
3. Implement read-only Tasks adapters to existing /api/crons routes with runner ownership.
4. Implement read-only Kanban board/detail adapters to existing /api/kanban routes.
5. Add confirmed, correctly scoped mutations only after receipt and approval contracts are complete.

## Follow-up review: race corrections (required before rollout)

Review of b9db8978 identified three correctness blockers. The follow-up change fixes them:

1. Stop captures the displayed session/request synchronously in the button callback, before scheduling/awaiting refresh. The refreshed request must still match that exact identity; a successor is never retargeted. A late cancellation response cannot replace a newer displayed request.
2. Authoritative cancelling/cancelled/execution_unknown from any surface pauses local follow-up draining. Each pending message retains its session identity. Drain requires a completed fresh control read, not a skipped/in-flight poll. Sending a new message does not implicitly resume retained follow-ups. Resume queued messages is an explicit action, enabled only when this session has retained messages, no active turn, a successful control read, and no unknown outcome. Acknowledging the settled request prevents the same old cancellation record from immediately pausing an explicit resume again.
3. Voice admission checks epoch, session and original client request ID before writing shared identity or starting a stream. A late old admission with a prior Stop gets one scoped cancellation against its own captured ID; its receipt/error is recorded separately and cannot overwrite a newer turn. Old errors likewise cannot change newer state.

Minimal check: three deterministic, suspended-admission/refresh race fixtures in StopRaceTests, plus the prior three StopControlTests. All six passed; the Swift app target built as part of that invocation. No additional backend tests were needed for this frontend-only follow-up.

## Closeout diagnosis and rollout requirements

At 2026-10-19T15:42:51 UTC the existing authenticated Gateway reported version 0.13.0, source checkout /Users/matthewjenkins/GitHub/JaegerAI, commit f34449e556c2e5778c95be8724836b616a01ca9b and live owner PID 58573. The commit is the checkout head reported by health, not a cryptographic fingerprint of all already-loaded Python modules. No active Gateway sessions were reported at that snapshot; this does not prove all external children or future scheduled work are idle.

The failed tool record identifies call/activity tool_e4bba079f2b243d589583d9aabef9ada and failure after 600.469s. Recorded arguments are detail/input_path/integrity_policy, with no output receipt path, remote job ID or remote cancellation handle. These scoped records cannot prove whether an external REA worker completed. One ordinary scoped reconciliation returned HTTP 409 at 2026-10-19T15:49:44 UTC; the request remains execution_unknown without replay or fabricated effect settlement.

The earlier process inspection was exactly `ps -axo pid,ppid,etime,comm` (filtered for Python/Swift names afterward). The shell returned default-sandbox Operation not permitted. This was not an automatic reviewer rejection. It was not retried or bypassed; no PID was guessed or killed.

Scoped app-registration lookup exposed multiple bundles with the same identifier. Reading their version stamps found:

- release candidate: ~/.jaeger/releases/0.13.0/app/JaegerAI.app, version 0.13.0, build 0.13.0+bbedb7b3, commit bbedb7b3d31ce90d449aef02e25905b6e0abf887;
- onboarding scratch: build 0.11.0-onboarding-test, commit ff91c90d0759193bc4e09219834fe8259f15b04b;
- older verification backup: build 0.11.0+7c4797a4;
- Desktop archive: build 0.11.0+1bec0ee6.

These are on-disk bundle revisions. The currently running bundle path is not established; no app was launched merely to inspect it. Default Applications/build locations were absent and the current app inventory did not identify a running match. Confirm the actual target bundle before approving replacement.

Proposed rollout, not performed:

- Review the Stop commit and its race-fix follow-up as a pair. b9db8978 alone is not the rollout candidate. Keep Skills changes and the unrelated two-file native-context draft separate. The original Stop patch applies cleanly to current f34449e5 in a read-only git apply --check; the final combined patch needs the same integration check before packaging.
- Integrate approved Stop source into a dedicated release source base; preserve current checkout/other worktrees. Rebuild/sign the native Swift app into an external candidate directory using JAEGER_SWIFT_BUILD, record commit and source fingerprint, and retain the old target bundle before replacement. Do not overwrite a release directory or select an old scratch bundle by bundle ID alone.
- Load the new Python Gateway server and MCP client together using a planned Gateway daemon restart after rechecking active work. That restart briefly disconnects all REST/SSE clients, stops the owner/background producers, invokes orchestration cancel_all and cancels running Gateway tasks. It can affect unrelated IDE work even when the session list is empty; it is not a scoped way to finish the unresolved REA effect.
- Relaunch the identified native app to load the rebuilt Swift client. Its subprocess bridge must be recreated to use the new turn-ID behavior. The bridge's Python protocol already accepts turn_id. WebUI, runner-local scheduler, REA server, model/provider configuration and credentials do not need a rebuild/configuration change for these Stop repairs. No blanket service restart is justified.
- After explicit deployment authorization, verify health/source revision and bundle build stamps, recovered request discovery, exact cancel request identity and honest settlement. Any new live validation turn/tool requires separate authorization; existing fixtures are not installed-app acceptance.

Rollback: retain previous Gateway source/environment revision and exact native app bundle/build fingerprint before deployment. Revert only the approved Stop commits (or switch the deployment source to the saved revision) and restart the Gateway in another idle window, then restore/relaunch the saved native bundle. No DB schema migration is introduced; do not roll back databases, erase logs, delete effect records or mark execution_unknown complete. Rollback also has the same client/worker interruption risk as rollout.

Concrete remaining uncertainty: the remote REA operation has no conclusive receipt/handle in supported scoped observations. Safest immediate containment is to leave the original session quarantined as execution_unknown and never replay it. A new conversation would isolate new work but would not prove the REA operation stopped. A Gateway/shared MCP restart is a separate maintenance decision with broad disruption, not proof of remote completion. The next rollout prerequisite is identifying the actual app bundle and approving an idle maintenance window for the corrected Stop pair; no broad kill permission is requested.
