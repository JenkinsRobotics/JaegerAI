# Integration release goal — execution record

Goal started 2026-09-06 against `737935d`. Release status: **NOT READY**.
Scope: execute `ROUNDTABLE_AUDIT_AND_PROMPT.md`; preserve native runtime ownership.

## Authority

The user explicitly approved pairing the existing local OpenClaw adapter with
operator.read, operator.write, operator.approvals, and configuring/testing direct
Desktop, Documents, Jenkins_Robotics and Personal-Drive mounts. Tool actions are
not automatically approved. macOS privacy prompts still require the user.
Local logical commits are authorized; no push or public release requested.

## Acceptance matrix

| Area | Implementation | Automated | Live | Remaining |
| --- | --- | --- | --- | --- |
| Quick/mention eligibility | Fixed | Reproduced before fix, passing after | Pending | Browser checks |
| Partial/error and EOF classification | Fixed for Roundtable legacy SSE | Reproduced before fix, passing after | Pending fault injection | Native transport migration |
| Anonymous member-session collision | Reject missing member ID; isolated anonymous table for direct callers | Passing | Pending | Durable table contract |
| A2A scoped cancel | Task-owned IDs; cancellation confirmation in bridge reply; context-scoped sessions | Concurrent A/B cancellation test passing | Pending deploy | Durable task store/restart tests |
| Test isolation | Supervisor honors isolated JAEGER_HOME; guard excludes exact background health snapshot | Full root suite passing with live supervisor | Supervisor left running | Continue isolated integration coverage |
| OpenClaw pairing | Approved existing identity with requested scopes only | Signature/translation/cancellation tests | Native stream, real file tool and confirmed abort passed | Actual approval denial blocked on native test-session admin; WebUI flag still off |
| Hermes native API | Native API launcher, structured SessionDB resumption, separate launchd supervision | Six focused tests passing | Streamed first turn and random-code recall passed after restart | Roundtable integration and native control tests |
| Native durable admission | Private ownership registry; Jaeger receipts and authenticated reconciliation | Concurrent observers/registries, wrong identities, unknown results and terminal recovery tested | Bridge contract 14 deployed; adapter recovery still staged | Hermes/OpenClaw reconciliation; durable UI route pins, bounded event storage and retention |
| Roundtable lifecycle/control/auth | Opt-in native member Runs, durable table ledger, scoped Stop/approval/retry | 24 isolated Roundtable tests pass | Native backend two-turn streaming/recall passes; WebUI remains legacy | UI integration and live control/fault/restart tests |
| Legacy Jaeger/OpenClaw ingress | Shared credential/origin/body guards; truthful unsupported Stop; bounded connection server | Unauthorized request reproduced before fix; 122 focused tests pass | Not deployed | Coordinated sender-first rollout and live negative/positive checks |
| Timeout layers | Native table has separate queue/idle/tool/approval and optional overall total | Virtual-clock progress, heartbeat and stall tests pass | Existing legacy 90-second setting remains | Upstream transport layers and real long-running control tests |
| Coordination/evidence/consensus/ledger | Six native workflows, explicit ballots, attributed tool receipts, durable tasks/decisions and chair rotation | Isolated workflow/ballot/assignment/rotation tests pass | Native ask/discussion/recall passes in isolated table; legacy UI still live | Actual task delegation and UI evidence/decision display |
| Group-chat UI/controls | Not complete | Pending | Existing Markdown presentation | Partial member events, selectors, browser tests |
| Provider/thinking/usage | Not complete; official contract/pricing research recorded in OLLAMA_VERIFICATION.md | Pending | Existing defaults preserved | Native session-local overrides, installed-version checks, attributed usage |
| Workspace/private NAS access | Reversible expansion implemented | 19 focused tests passing | Rolled back: local roots pass; NAS checks fail | Resolve NAS filesystem semantics before retry; originals running |
| Honcho per-agent verification | Not complete | Pending | Not retested | Isolated LAN write/retrieve receipts |
| Recovery/deployment/CI | Not complete | Pending | Supervisor active | Layered readiness, verified repairs, overlay CI/build/rollback |

## Evidence so far

- Six audit regressions failed before their fixes (selection, mention token,
  partial+error, premature EOF, anonymous identity, unknown A2A cancellation).
- Focused affected/neighbor suites: 128 passed in 6.92 seconds.
- Full root suite after first repair phase: **3,601 passed, 11 skipped**, one
  `audioop` deprecation warning, 107.45 seconds, seed `20260906`. No supervisor
  pause was required. Later phase changes require their own verification.
- A bridge queue test exposed a sleep-based scheduling flake; replaced sleeps
  with explicit worker-entry and queue-acknowledgement synchronization.
- Existing bridge reply shape is preserved for clients without scoped turn IDs.
- OpenClaw device approval used the exact inspected request ID and requested
  scopes. No permanent tool grant or automatic approval was enabled.
- Direct native OpenClaw probe returned and streamed `OPENCLAW-NATIVE-READY`
  in 2.78 seconds. This is a chat transport test, not a tool/approval test.
- Native Hermes Runs initially failed a random-code recall test: its Runs path
  supplied empty history instead of restoring SessionDB. The Jaeger-owned shim
  now restores native structured history at execution, retaining tool-call IDs.
  Six focused launcher/session/service tests pass. After installing the separate
  `com.jenkinsrobotics.hermes-native-api` supervisor, live session
  `verification-native-hermes-6bc64494965d4e06a91b4d0c9c05aaa8` passed both turns
  (5.90s and 1.33s). Default Hermes WebUI routing was not changed.
- A throwaway container successfully mounted Desktop, Documents, Jenkins_Robotics,
  and Personal-Drive during preflight, then exited and was automatically removed.
  This verifies mount startup, not actual-user read/write. Working container
  mounts remain unchanged until the managed update and access probes pass.
- OpenClaw native file tool returned the real README first line in 3.44s, with
  `tool.started` and `tool.completed` events. Confirmed abort probe
  `346a39f6dd104142ab02f850ab1ebd20` completed in 0.16s, with an explicit native
  cancellation confirmation. Local cancellation intent is now separate from
  confirmation; a native completion that wins the race is reported completed.
- Approval-denial probing did not pass: harmless print commands ran under the
  existing native policy without prompting. Tightening only a new verification
  session to Guarded was rejected by the installed gateway with
  `missing scope: operator.admin`. The normal adapter's scopes were not expanded.
  A separate temporary admin verification identity was requested from the user;
  pending response. Native permission errors are now categorized separately from
  transport failures. This remains an explicit release gate, not a passing test.
- Control/failure focused tests after these changes: 42 passed in 1.97s.
- A further bridge race test reproduced false cancellation confirmation when
  the native turn completed normally after receiving Stop. Scoped replies now
  confirm only an actual native `interrupted` halt or skipped dispatch. Bridge
  and native Runs focused suites: 110 passed in 4.72s. Not yet deployed.
- Four-profile live WebUI check: Hermes/default (`9970fce7951f`), Jaeger
  (`aff87f9072c9`), and OpenClaw (`5f02ecb65346`) passed two-turn recall.
  Roundtable (`b250936ef21a`) failed: all three initial answers passed, but
  Hermes' discussion CLI invocation returned only a resume notice and an error.
  Native Hermes Runs recall worked independently; the following repair replaced
  the CLI path while preserving its existing native session.
- Hermes Roundtable path repaired in `da1402e`: authenticated native Runs instead
  of CLI, with exact legacy named-session/continuation lookup. Canary recovered
  `ROUNDTABLE-b25093` from the previously failing session. Reloaded only the
  isolated native API and Roundtable adapter after idle checks. WebUI session
  `5fadef7a8b6b` then passed all three initial answers, all three discussion
  answers, and follow-up recall (43.5s/48.0s cumulative). Individual profiles
  were not restarted. Legacy Markdown cannot relay approvals: any such request
  is denied and reported as `approval_required`, never auto-approved or counted
  as a successful answer. Structured approval UI remains a release gate.
- Provisioned only Roundtable's missing profile gateway credential (private,
  preserved model/provider/comments, no rotation of Jaeger/OpenClaw keys).
  Deployed its authenticated ingress: a real credential-free execution request
  now returns HTTP 401. Legacy cancel no longer falsely claims that native work
  stopped; it returns unsupported-control, or 404 for an unknown run.
  Post-deploy four-profile WebUI two-turn tests all passed: Hermes/default
  `7908ba06eedb`, Jaeger `6c1d3aebb07e`, OpenClaw `3667b73c3640`, and Roundtable
  `44aabc9f0911` (all three answer/discussion members, then recall; 20.8s total).
  Native control, UI, long-running/failure and release gates are still incomplete.
- Native Runs now reserves session ownership transactionally before worker start,
  imports unreconciled legacy receipts, and retains ownership after ambiguous
  transport failure or adapter restart. Proven native completion/cancellation or
  pre-dispatch rejection releases the owner. Native session/run IDs and execution
  uncertainty are recorded; cancellation intent survives a control-send failure.
  Tests reproduce the previous duplicate-admission failure across restarts and
  independent registry instances. Native reconciliation of uncertain owners is
  still required before deploying the remaining adapters; the Roundtable Hermes
  guard is live and deliberately retains uncertain owners without blind replay.
  Combined native/workspace/supervisor focused suite: 51 passed in 1.80s.
- Full root regression after durable admission/workspace diagnostics/supervisor
  fixes: **3,630 passed, 11 skipped**, one audioop deprecation, 104.40s, seed
  `20260906`. Live post-rollback Hermes native recall passed (6.64s/1.06s);
  OpenClaw native README tool passed (3.68s) and confirmed abort passed (0.23s).
  OpenClaw's read-only `agent.wait` reported the completed probe as `ok`, but
  reported the aborted probe as `timeout`; absence from this lookup is not
  accepted as evidence of cancellation/completion for future reconciliation.
- Supervisor repair commands now require an immediate readiness recheck before
  being reported successful, including the explicit repair CLI's exit status.
  Failed probes/repairs are isolated per component; exact container inspection
  has a five-second bound, unknown state fails closed, and a failed stop cannot
  fall through to start. Nine focused supervisor tests pass. Layered dependency
  health and active-work maintenance guards remain pending; this is not complete
  recovery certification. These source changes have not yet been deployed.
- Workspace expansion `6c4400f` failed its actual-user access gate and automatically
  restored both original containers, the manifest, configuration, and monitoring.
  The failed `jaeger-hermes-workspaces` replacement is retained stopped; it must
  not be started alongside the original (same published port/shared state).
- Isolated image probes as Hermes UID 501 passed GitHub, Desktop, Documents,
  authenticated host MCP, Jaeger/Roundtable health and the A2A card. Both SMB NAS
  roots failed cleanup with ENOTEMPTY. An isolated Jenkins_Robotics file test
  also failed with ENOENT when reading after a successful rename. Cleanup can mask
  earlier failures. Bounded cleanup retries did not resolve
  the live failure. Mount startup is therefore not accepted as proof of RW access.
  Probe diagnostics now retain the first failed operation, and deployment keeps
  failure receipts privately instead of discarding nonzero probe output.
  No share permissions, NAS configuration, or kernel settings were changed.
- OpenClaw-image UID 1000 probes independently passed Desktop/Documents (2ms
  each) but reproduced ENOENT after rename and ENOTEMPTY cleanup on BOTH NAS
  roots (25/31ms to failure). The identical file lifecycle passes directly on
  macOS (34/40ms), isolating the failure to the container/host SMB mount path.
  All identified empty probe directories were removed from the host; no user
  files were deleted. Installed Apple Container CLI 1.3.1 has no SMB driver flag;
  direct guest SMB remains an upstream feature request:
  https://github.com/apple/container/issues/1911 . Do not change kernels or NAS
  security settings as an unreviewed workaround.
- Actual container-side authenticated host-tool probes passed create/read/edit/read
  on both NAS shares for both agents (0.23–0.31s). Temporary files/directories
  were cleaned up on the Mac; no user files changed. Host tools therefore offer
  a working NAS path while direct mounts remain unsafe. OpenClaw's current
  credential resolves to effective host identity `hermes`, confirming the
  previously documented alias debt; distinct identity/grant routing still needs
  repair. `scripts/verify-host-nas.py` reports that distinction explicitly.
- Latest full root regression: **3,651 passed, 11 skipped**, one audioop
  deprecation, 109.88s, seed `20260906`. Monitoring remained active. The added NAS
  helper subsequently passed its focused target/identity guards and live checks;
  this is not an upstream/browser/release certification.
- Later non-regression live WebUI check (no services restarted): Hermes/default
  `1e09212cda6f` passed two turns in 9.0s; Jaeger `2de5fbd1bd43` in 13.2s;
  OpenClaw `3ace4d9a8aab` in 6.8s; Roundtable `eb3ab43c2d67` in 29.1s.
  The first table turn checked all member answers and one discussion; the second
  used `/quick @jaeger`. This verifies the existing deployed baseline, not the
  staged ingress/recovery changes or full provider/control parity.
  This live check overlapped a root test run: all 3,718 tests passed, but the
  live-file isolation guard correctly failed because the verification generated
  native receipts. Do not accept that run as a clean regression gate. Repeat
  serially after live checks finish, without changing the guard or deleting
  verification/native session evidence.
- Clean serial rerun after that live check: **3,718 passed, 11 skipped**, one
  audioop deprecation, **109.24s**, seed `20260906`, exit 0. The isolation guard
  remained enabled; no service or monitoring restart was needed.

## Deployment boundary

### Native Jaeger recovery

Bridge contract 14 adds instance-owned private SQLite turn receipts. A scoped
turn ID is admitted once; its terminal result is saved before the transport
reply. Duplicate IDs cannot execute again. Missing receipts, receipts belonging
to another session, and unfinished work from an earlier bridge process remain
unknown. The pending scoped-turn capacity is 256; this is not yet comprehensive
retention or admission control for legacy/unscoped traffic.

The Jaeger adapter now offers authenticated `POST /v1/runs/<id>/reconcile` with
an empty JSON body. It queries the original native turn/session, never sends a
new prompt. Only matching native terminal evidence releases the session lock.
Recovery preserves the previous failure event and appends `run.reconciled`,
restoring the native final output when available. A per-run kernel file lock
excludes recovery while another process still observes or writes that run.
The query has a ten-second socket wait; missing/unsupported/ambiguous results
retain ownership. No user-facing retry/recovery button is implemented yet.

Focused bridge/native receipt/adapter tests: **131 passed**; three additional
bridge-client contract tests pass for uncertainty propagation and query timeout.
The full regression initially caught an omitted desktop surface classification
for the new query. After classifying it honestly as bridge-only, the full root
suite passed: **3,680 passed, 11 skipped**, one audioop deprecation, 106.81s,
seed `20260906`. This run predates the next legacy-ingress regression tests.
The bridge portion was subsequently deployed with the worker-context fix below;
the adapter recovery endpoint and live restart/disconnect recovery remain staged
or unverified. Hermes/OpenClaw need their own trusted reconciliation implementations;
OpenClaw lookup timeout must not be interpreted as confirmed cancellation.
Native Runs ingress additionally rejects browser Origins, transfer encoding,
duplicate Content-Length and oversized bodies, with a bounded body-read wait.

### Current running services

Legacy ingress hardening is staged: Jaeger/OpenClaw now share native-route
credential/origin/body validation even when native mode is disabled. Legacy
Stop returns unsupported for a known run and does not mutate its native status.
All three profile servers use a 64-connection bound, with a 15-second idle/header
wait and an explicit pre-dispatch 503 when full. This bounds request observers,
not all background execution or historical event storage; those gates remain.

Deployment order matters: restart the updated Roundtable sender first (it now
sends the selected member's existing gateway credential), then deploy enforcing
Jaeger/OpenClaw adapters after idle/rollback checks. All three profile credentials
were checked for presence without printing them. Do not enforce member ingress
before its currently-running Roundtable sender has been upgraded. Existing
individual WebUI gateways already have profile credentials. No secret was rotated.

Roundtable fixes through `d53b0f5` are deployed, including its native Hermes
client, authenticated legacy ingress and truthful unsupported cancellation.
The scoped bridge fixes through `43ba728` are now loaded. A2A and remaining
Jaeger/OpenClaw adapter changes are committed but not deployed. Supervisor source
fixes are also staged, not loaded.
The Hermes native API service is live inside the existing container on port 8645,
authenticated by a private credential and without a published Mac host port.
OpenClaw pairing is live; its native WebUI feature flag remains disabled pending
approval verification. Workspace expansion rolled back; originals retain their
GitHub-only managed mount additions. Existing user conversations were not
rewritten; live tests created labeled verification sessions.

Before deployment: record the active commit/image/config backups; verify no
wanted run is active; use explicit service targets; preserve rollback containers;
restore any paused monitoring; test all four profiles and native controls.
Do not mark the goal complete while required matrix cells remain unverified.

### Native Roundtable and genuine Jaeger streaming

The new opt-in `TableService` coordinates native member Runs and persists table
preferences, dispatch intents, bounded current-round prompts, decisions, task
owners, and evidence separately from native chat history. Modes now have
distinct workflows. Strict ballot validation retains failed/missing/minority
votes; truncation cannot establish consensus. Per-member retry preserves the
native session and does not rerun everybody. Progress budgets do not treat
heartbeats as useful work or impose an implicit overall deadline. See
`ROUNDTABLE_NATIVE.md` for the staged API and limitations.

The first real native table test found that Jaeger only emitted final text.
Reproductions showed that both fresh/reused model workers and parallel tool
workers lost turn-scoped ContextVars. Fix `43ba728` enters a fresh copied context
per worker invocation. The three reproductions pass after failing before the
fix; combined bridge/adapter suites passed **149 tests**, and native package/
neighbor suites passed **99 tests**. Persistent workers do not retain a previous
turn's stream destination.

After confirming WebUI had zero active runs/streams, all 50 native sessions were
idle, and no cron jobs were running, restarted only
`com.jenkinsrobotics.jaeger-bridge`. Source rollback archives for baseline
`737935d` and target `43ba728` are retained privately under
`.jaeger_ai/shared/deployments/bridge-20260906-stream-context/`.
Ready handshake and contract 14 passed. No provider/profile/mount/grant settings
changed and neither agent container was restarted. Old cognition ledger rows
still marked active are not treated as evidence of running native chat workers;
ledger lifecycle cleanup remains a separate audit concern.

Live native table `verification-roundtable-native-3d77a22ad56941c8a6b25d75e6b46494`
passed: all three first answers streamed before their native workers finished,
all three performed one discussion, and all three recalled the check word on the
second turn with identical native session keys. That turn's initial prompts
contained neither the check word nor a copied shared summary. Total turn times
were **32.49s and 59.07s**, including synthesis. No tools or approval grants were
used. Native receipts are in the private verification directory
`/var/folders/fk/gjrpb6d55td2y2ffmsrsv76c0000gn/T/jaeger-roundtable-native-jcn9i1mz`.
Subsequent source review replaced random per-turn chair choice with actual
persisted rotation; its restart/rotation test passes, but that refinement was
not part of the preceding live run.

Post-bridge-deploy existing WebUI two-turn recall passed for Hermes/default
`527af225af9b` (9.0s), Jaeger `b045ae9251fa` (10.4s), OpenClaw `2517689f5e04`
(4.1s), and Roundtable `5b9aa06f3986` (21.0s; all first-round members and
discussion, then `/quick @jaeger`). These checks preserve the current profile
paths; they do not certify all provider overrides or tool/control parity.

The native Roundtable flag stays OFF. Browser rendering/selectors, final-text
replacement handling, durable route/control recovery, bounded event storage,
native permission/failure tests and remaining acceptance-matrix gates must pass
before activation. Both engine and ledger remain staged, not advertised as
completed group-chat UI features.

The first full regression of this phase passed **3,745 tests, 11 skipped** in
111.36s with seed `20260906`, with the isolation guard enabled and all live probes
finished before the run. Final review then reproduced explicit run-ID reuse
overwriting a completed receipt and dispatching again, even after restart or
under a different session. Admission now retains single-use ID tombstones and
rejects existing receipts; releasing an active owner does not release its ID.
Two before-fix failures now pass, with a separate pre-dispatch tombstone test.
These are control receipts, not native session/history changes. Comprehensive
storage retention remains pending.
