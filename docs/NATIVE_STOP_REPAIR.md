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
