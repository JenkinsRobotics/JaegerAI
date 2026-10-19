# Mac app integration and completion

Owner: one implementation owner in the canonical `~/GitHub/JaegerAI` checkout.
Updated: 2026-10-19. IDE is held unchanged for this work.

This is the current Mac continuation record. Older `NATIVE_*` handoffs describe
individual source candidates, not the current integration or installation state.
Runtime data and build artifacts remain outside the repository.

## Preserved and reconciled source

The [worktree inventory](2026-10-19-worktree-inventory.json) records current
external heads, unfinished files, byte hashes, and preserved repository refs.
No external worktree was deleted, reset, checked out, or overwritten in this pass.
Preserved refs point into this repository's Git object store; unfinished IDE work
has a standalone snapshot commit, without altering its original index or files.

| Source | Canonical disposition |
| --- | --- |
| Native panels, recovery, approvals, unfinished scheduler files | Integrated through `13132e00`, `5f4195b9`, `d921b779`; external native-panels head is an ancestor of main and clean. |
| Speech ownership `7dcbaf4a` | Ancestor of main; clean source retained. |
| Combined Mac candidate `f829f73d` | Four remaining commits are patch-equivalent to main, including cancelled speech drain outcomes. No reimport needed. |
| Stop candidate `7422d707` | Four remaining commits are patch-equivalent to main; scoped cancellation and queue guards retained. |
| Prior `mac-grok-ui`, `team-rea`, UI rebuild branches | `git cherry HEAD <branch>` reports no outstanding patches. Prior dirty UI preservation is in `6434a8fa`; original reconciliation receipt/backups remain under `~/.jaeger/reconciliation/2026-10-19-worktrees`. |
| Agent bridge / agent bridge 2 | Heads already ancestors of main; clean. |
| Unfinished external IDE tree | Snapshot under `preserved/20261019/jaeger-ide-fix`; main contains newer accepted IDE behavior. Do not replace current IDE with this snapshot. |
| MCP Events `3153b724` | Three unique commits preserved under `preserved/20261019/mcp-events` (also mcpev-wt). Not part of Mac integration: introduces OAuth/event facade changes outside this task's security-change authorization. Nothing deleted or silently declared integrated. |

## Existing integrated capabilities

- Conversations: Gateway durable empty-session creation, history snapshots, matching
  request SSE replay, reconnect by snapshot, stale-selection guards; observation
  never resubmits work.
- Stop: exact selected request cancellation, retained partial text/queued messages,
  unknown settlement shown honestly; no fallback execution after Dispatcher cancel.
- Approvals: current session/request/profile binding, stale-context rejection,
  decision receipt reconciliation, no resend after uncertain decision.
- Schedules: Gateway CRUD, pause/resume, run-once through task owner, immutable
  operation receipts and unknown-write protection; history uses owner records.
- Board: Gateway-owned proposals, versioned edits/approval, cancellation and run
  history. No simulated task progress or local completion.
- Voice: existing STT/recording, serialized speech ownership/drain, speech status,
  measured output amplitude and avatar integration. Physical audio acceptance is
  distinct from decoded/rendered audio or tests.

## Repairs in this pass

- Show recovered tool/delegation activity independently of pending approvals;
  refresh it during local bridge turns and consume matching live SSE activity.
- Decode actual nested handoff records, including parent, child and agent identity.
  Snapshot projection excludes worker output, prompts and tool arguments.
- Keep unknown board states visible; distinguish paused work from proposals and
  offer proposal editing only with explicit unapproved provenance.
- Refresh visible schedules and board every three seconds through existing reads.
  Show next/last firing timestamps without treating firing as execution success.
- Give voice view a direct Stop speech control and measured microphone level;
  never auto-speak a failed reply as if it succeeded.

## Evidence and deployment

Baseline canonical verification passed the IDE/frontend/backend stages; complete
result and final focused/native acceptance will be recorded below before delivery.
Production Gateway PID 58573 was observed unchanged during implementation.
During native acceptance, UI selection launched an unintended second app without
the isolated environment. That app ran the old installed `stack up`, replacing the
managed Gateway with an installed copy on retired port 8810. Its startup process
and that verification app were stopped. Gateway restoration to canonical source
and port 33418 is prepared and awaiting operator coordination; it is not yet done.
Source fixes remove implicit shared-service startup/shutdown from ordinary app
launch/quit and bind the source bundle/launcher to canonical code outside repo cwd.
No new operator credentials, grants, tunnels or security settings were introduced.

The existing REA setup and Grok analysis at
`~/Documents/Codex/2026-10-19/task/Grok-Bot-analysis.md` were consulted for demonstrated
gaps (recovery, scoped approvals, real tasks and delegated identity). Proprietary
Grok application code was not imported. Existing REA fixture/native limitations
remain as recorded in `REA-remediation.md`; none was bypassed to implement UI.

## Remaining acceptance work

- Build and exercise the native app against an isolated existing Gateway fixture.
- Confirm the selected live installation and coordinate any required Gateway/app
  interruption before applying it. Old loaded Python modules do not become new
  merely because checkout HEAD changes.
- Physical microphone, recognition and audible playback/avatar synchronization
  require usable existing audio hardware/permissions. Do not grant access silently.
- Preserve the previously unresolved REA execution outcome; do not retry it or
  infer remote termination from a local Stop.

## Checkpoint before the queued assessment

Matthew requested ending this implementation turn so the already-queued Codex
conversation message beginning "Matthew's immediate priority is assessment first,
before broad edits" can run. It is a Codex Queue item, not a Jaeger inbox message.
Do not duplicate it or keep searching other systems. Add these assessment criteria:
agent profile right-click actions; settings grouping and completeness; dynamic
window/text sizing; persistent independent agent identities, per-agent context,
resume and delegation; background sessions with preserved history.

Gateway restoration was explicitly approved. The first restoration was terminated
by the expired existing menu-bar lease. No lease policy was bypassed. The canonical
native app was opened as the normal menu-bar owner; only the Gateway launch job
was then restored. Final read: `/health` status `ok`, port 33418, PID 59577,
source `~/GitHub/JaegerAI/jaeger_ai/core/gateway/server.py`, existing store
`~/.jaeger/gateway_sessions.sqlite3`. Other launch jobs were not restored or
reconfigured by that approved action. The earlier unintended `stack up` did affect
other services; those effects remain disclosed, not silently treated as restored.

Current native app: external signed development bundle
`~/.jaeger/scratch/mac-integration-20261019/swift/JaegerAI.app`, PID 59466,
normal lifecycle owner. Do not quit/restart it during assessment without accounting
for the Gateway's existing menu-bar lease. It is a development build from this
turn's source, not a qualified release install. Its recorded build commit predates
this checkpoint commit. Production bridge/WebUI readiness remains incomplete.

Evidence:

- Baseline `./scripts/verify.sh`: passed all tiers (`/tmp/jaeger-mac-start-verify.log`).
- Swift full run: 216 tests, 3 skipped, no failures. Later focused lifecycle run:
  14 tests passed, including failed-recovery visibility and nested delegated identity.
- Focused Python: 10 passed before the final error-projection test; final recovery
  and launcher run: 8 passed (`/tmp/jaeger-mac-recovery-final.log`).
- Final canonical verification was attempted but exited 1 because its disk guard
  observed concurrent live Gateway writes to `background_producers.json`,
  `background_producers.lock`, and `entity.resident.lock`. It must not be reported
  as passing (`/tmp/jaeger-mac-final-verify.log`). Do not stop the live Gateway just
  to make that guard pass without coordination.
- Signed bundle built externally. Native UI proved durable New Chat and send
  admission against an isolated actual Gateway. A provider failure was visibly
  retained after recovery; no successful native response was proven in this pass.
- The isolated fixture's custom provider configuration was rewritten during its
  app startup/first-boot path. Root cause and preservation of custom provider
  endpoint/key references need assessment; do not create credentials to mask it.
- Existing voice audio artifact/telemetry from the earlier integration is still
  preserved. No new microphone permission, physical recognition, audible playback,
  or avatar synchronization acceptance was claimed.

Independent isolated test Gateway remains at port 60264, PID 57283, state
`/tmp/jaeger-mac-20261019`, using already-existing isolated caller-token files.
The older test Gateway at 56062 was left intact. No test state was deleted.

Next action: consume the queued assessment, then prioritize its demonstrated
Mac app failures. Do not start another broad implementation/audit in parallel.
