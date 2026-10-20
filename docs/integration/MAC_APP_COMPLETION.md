# Mac app integration and completion

## Authorized runtime follow-through — 2026-10-19

Sole coder/runtime owner. Matthew now authorizes required local Gateway33418/WebUI8790 and current newer shell replacement, plus safe visible comparison with open Grok. No old fallback, unrelated workers, credentials/permissions/network changes, or unknown-outcome replay. Startup inspection reproduced a redispatch path for `execution_unknown` despite no proof of effect outcome. Removed automatic redispatch; startup now reports preserved unknown rows for explicit reconciliation. An isolated regression verifies request/history immutability and no scheduled execution. Earlier source-only restrictions below are historical. Live results will be appended after verification.

## Explicit foreground lifecycle startup — 2026-10-19

**Source checkpoint; production unchanged in this pass.** Reported newer shell PID 99725 was confirmed read-only at the supplied external bundle path. Opening/switch approval exists, but this coding pass explicitly forbids runtime changes. Earlier runtime observations below are historical.

- Cause: ordinary launch waits for a healthy Gateway before acquiring its lifecycle lease; an expired `menubar` lease makes the Gateway exit before health succeeds.
- Added **explicit** `--own-production-lifecycle` startup. Requires enabled existing lease policy, production stack mode, visible/non-verification shell, explicit absolute `JAEGER_STATE_DIR`, and no separate lifecycle-lease override. Default development bundles still have no lease. No Gateway or stack command is invoked by this path.
- `JaegerShellApplication` selects this path instead of the health-dependent acquisition. `StackController.acquireForegroundOwnership` resolves the existing Stop latch. `ForegroundLease` holds a nonblocking advisory owner lock, refuses a recent legacy beat, foreign/corrupt lease, or live recorded shell PID, and atomically writes this running shell's actual current heartbeat/PID. `LeaseBeat` renews every two seconds with App Nap disabled. Nothing clears Stop, removes the lease, or writes `beat_at: 0` in this mode.
- Global Stop engaged/unreadable prevents acquisition. Observing Stop during renewal latches refusal for this shell instance, even after Stop is released elsewhere. The last real beat remains; normal Gateway suspension/shutdown policy applies. Quit relinquishes the lock while retaining the last heartbeat, so this explicit owner mode intentionally does **not** promise that Gateway outlives shell quit. Closing its window still leaves the menu-bar process alive.
- Ownership lock protects cooperating explicit owners; PID metadata protects a recorded live process even with an old beat. Historical PID-less expired leases cannot prove whether an obsolete/noncooperating writer still exists. Coordinate replacing the known running shell first; do not run two shell owners. Ordinary health-dependent startup and legacy/dev retire behavior are otherwise unchanged.

**Focused verification:** 13 isolated Swift tests passed: four new filesystem ownership/Stop checks plus existing lease-policy/contract tests. They cover expired offline takeover with a real current beat and 0600 file, lock contention, stale live PID, recent legacy owner, corrupt/foreign lease, Stop before/after acquisition, no automatic resumption, and retained heartbeat on relinquish. No network listener, Gateway, app or service was launched by the tests. External scratch: `~/.cache/jaeger/verification/lifecycle-startup-20261019/scratch`. Native executable compiled during these checks. No broad suite or UI rebuild is needed for this native-only change. Isolated replacement bundle assembled and ad-hoc signature verification passed at `~/.cache/jaeger/verification/lifecycle-startup-20261019/native-shell/JaegerShell.app`, build `0.13.0+3d9e352d` from source commit `3d9e352d`. It was not launched, installed or selected. Logs are preserved beside the bundle at `tests.log` and `build.log`. The pre-existing VoiceController Sendable warning remains; no new compilation failure. Read-only post-build process inspection still showed PID 99725 using its original supplied bundle. Native source hygiene scan found no in-tree Swift build, Python bytecode or pytest cache output.

**Exact later launch procedure — NOT executed; coordinated runtime step still pending:** first coordinate replacement/quit of PID 99725 and verify no other shell owner; do not overwrite its running bundle. Run the replacement executable directly (not through an environment-losing `open` invocation):

```sh
JAEGER_SHELL_LEASE=1 JAEGER_SHELL_STACK_MODE=production JAEGER_STATE_DIR="$HOME/.jaeger" \
  "$HOME/.cache/jaeger/verification/lifecycle-startup-20261019/native-shell/JaegerShell.app/Contents/MacOS/JaegerShell" \
  --own-production-lifecycle
```

Use a clean launching environment with `JAEGER_SHELL_NO_LEASE`, `JAEGER_LIFECYCLE_LEASE` and unintended Stop-path overrides unset. Confirm the ownership-acquired log and genuine renewing `menubar`/shell PID lease before a **separately coordinated** canonical `JAEGER_STATE_DIR="$HOME/.jaeger" ./jaeger gateway daemon` start (or the existing exact managed job after read-only identity verification). Do not use shell Start Stack / `stack up` for this recovery. Verify loopback 33418 health/source and unchanged credentials/data afterwards. No service/job is changed in this source pass; production health and visible acceptance remain unknown here.


## Current bounded agent-management checkpoint — 2026-10-19

**Source only.** Sole owner; no other coder/worker resumed. Runtime migration remains unapproved. No app, service, login, token, security setting, permission or persistent-access rule is changed. The existing new `interfaces/ui` + `interfaces/macos-shell` architecture is retained. Prior checkpoints below are history, not current deployed behavior.

### Implemented behavior and storage

- Persistent display-name aliases, reversible navigation archive/restore, and shared ordered pins live in the existing Gateway SQLite store under the fixed `schema_meta` key `agent_presentation:operator`. Atomic transactions merge cosmetic patches without changing registry definitions. No second database, identity authority or runtime was added.
- `PATCH /v1/agents/{id}` accepts only `display_name` (trimmed/NFC, 1–80 single-line characters, or null to reset), `archived` and `pinned` (strict booleans). Immutable canonical IDs must match; unknown fields such as role/tools/permissions/context/owner/profile are rejected. No destructive delete exists. Built-ins and standing-specialist definitions are never rewritten by this layer.
- A display alias changes presentation only, including lead labels. It does not rename the entity, change its immutable name/ID, or move context/memory. Reset display name restores the underlying registry label. Lead/primary/system agents cannot be archived or pinned; internal/runtime agents cannot be renamed through these controls. Protected violations return 409.
- Archive sets a presentation flag: the agent leaves navigation, while existing chats, history, active/background sessions, tasks, role, tools, permissions and context remain unchanged. The selected chat may remain open. Settings → Agents keeps archived agents discoverable with Restore, Rename, Reset display name and Pin/Unpin where permitted. Restore returns the same ID/history; no agent or conversation is recreated or activated.
- `POST /v1/agents/pins` accepts the desired ordered `agent_ids` plus `expected_agent_ids`. Changes persist for the local operator across authorized clients. A stale ordering returns 409 rather than overwriting another client's update. The UI serializes its own pin operations, refreshes before updating, and shows failures instead of claiming success. Up to eight pins; archived pins retain their slots until explicitly unpinned from Settings.
- Old device-local pins are retained, not silently uploaded or discarded. Supporting servers use shared state; Settings offers an explicit merge of device pins into available shared slots. Older/non-supporting connections keep the labeled local fallback.

### Ownership, authentication and profile boundary

The current authentication contract explicitly describes a **single local operator**. `owner:webui`, `owner:menubar`, `owner:cli` and other trusted surfaces refer to that operator; they are not independent human owners. Shared pins use that existing operator/state-root boundary. They are **not isolated per WebUI login or profile**, because the proxy presents one `webui` caller identity and provides no authenticated per-human ownership key. Multi-owner/user-private pins would require a separate approved ownership/authentication contract; none was invented here.

Both new mutation routes use the existing default `admin` scope. Existing read-only bridge/agent callers are not granted admin; prefixed outside callers remain unable to use these routes. Read-only callers receive no presentation-edit capabilities. WebUI proxying retains existing CSRF/authentication and honors the existing optional expected-profile precondition; no profile is switched and no new profile access is granted. Agent presentation is operator-global, not profile-local configuration.

Source evidence: `core/gateway/agent_presentation.py` (validation/projection/protection), `session_store.py` (atomic metadata/pin persistence), `server.py` (routes, authenticated capability projection, catalog/detail/summary presentation), `features/webui/api/jaeger_agents.py` (existing proxy/profile guard), `ui/src/agents/AgentManagement.tsx`, `AgentContextMenu.tsx`, `ui/src/App.tsx`, and `ui/src/api/{agentActions,gateway}.ts`. Skill-inventory failure no longer strips presentation metadata or accidentally changes capability reporting.

### Verification and exact limits

Focused Python checks: 17 passed, covering store reload, history/running-session preservation, immutable execution fields, validation, reset/restore, ordered pins and stale writes, canonical ID/protected handling, proxy/profile precondition, existing admin/prefixed scope rules, and read-only capability projection even with unavailable skills. Focused UI checks: 23 distinct tests passed across management, settings, menus, API requests, pins and details, including a full in-memory App flow that renames/archives/restores/pins the same agent after server acknowledgements. This fixture is not live acceptance. TypeScript and theme checks passed; final compilation results are recorded after the isolated builds below.

Evidence directory: `/Users/matthewjenkins/.cache/jaeger/verification/mac-agent-management-20261019-163701`.

No live HTTP listener was started by the checks, no credentials were created, and no production database was opened for mutation. The native shell source is unchanged by this feature pass; its final build is compile evidence only. UI/shell builds will be made once into isolated, unserved paths, not the default app selection or served UI cache.

**Final isolated compile evidence:** feature commit `565d682b` compiled successfully once for both shared UI (theme guard, TypeScript, Vite production output and no-mock check) and native shell (debug build/sign verification). UI output: `/Users/matthewjenkins/.cache/jaeger/agent-management-source-jderll6w/dist`. Shell output: `/Users/matthewjenkins/.cache/jaeger/verification/mac-agent-management-20261019-163701/native-shell/JaegerShell.app`. Source snapshot bytes and shell source hash match the feature source. Default served UI/index and selected shell build stamp were checked unchanged. No artifact was installed, launched or selected. Existing Vite chunk-size and Swift concurrency warnings remain; these are compile results, not live acceptance. A subsequent documentation-only commit records these results.

**Remaining/unknown:** live Mac right-click/edit/restore, native window interaction, authenticated end-to-end mutation/profile behavior, real two-device pin synchronization and background-session continuity still need coordinated runtime acceptance. Same-field cosmetic edits use last successful write; pin-list conflicts instead fail visibly. Multi-user/profile-private preferences, destructive delete, duplicate, templates and sections remain unsupported. Ambient/barge-in, camera/avatar/share presentation gaps from cleanup remain. Runtime blockers (old app PID 59466, test Gateway PID 8931/worktree, and previously absent 8790 backend) are not acted on here.

## Previous bounded source checkpoint — 2026-10-19

Sole owner; canonical repo. New `interfaces/ui` and `interfaces/macos-shell` only. Runtime migration is pending: no app/service was started, stopped, restarted, installed or switched. No candidate packaging. Earlier legacy cleanup is committed at `12235c56`, with the recoverable [Desktop archive and runtime blockers](SCOPED_CLEANUP.md).

### Actual behavior in this implementation

- Removed `HERMES_WEBUI_EXTENSION_SCRIPT_URLS=/extensions/jaeger_webui_branding.js` from `scripts/run-jaeger-webui.sh`. Canonical shared UI still serves through `features/webui/api/ui_shell.py`; absent builds return 503 and `/legacy` remains 404. Existing login/authentication and backend proxy remain unchanged.
- Agent right-click offers Open chat, Agent profile, Conversation history, Mark Read, device-local Pin/Unpin, and Copy ID. Open uses the existing per-agent home selection, not a new identity or fresh context. Profile/history use existing read-only panels. None activates a different persistent agent, wakes a worker, or clears history.
- Registry projections advertise explicit `ui_actions: {read: true}`. Frontend capabilities require that advertisement rather than guessing from identity/unread fields. Mark Read uses existing authenticated `POST /v1/agents/{id}/seen`; local seen feedback follows successful server acknowledgement. Older servers can use explicitly labeled device-local read marks. Pins are explicitly device-local.
- Copy ID uses the existing host clipboard API (native bridge on Mac); missing/denied web clipboard access rejects and reports failure.
- Identity review: registry supports create/set-active, not rename/delete/hide/duplicate/sections/template export. No new mutation route or expanded rights was invented. Unsupported actions stay hidden. Primary/native:jaeger and lead-role agents remain protected by the frontend even if a future server advertises destructive actions. Existing backend validation/authentication is untouched.
- General settings now edit device-local text size 12–22px (14 default), apply body/small/tiny font and line-height tokens immediately, restore on load and synchronize device-origin windows. Theme remains light/dark/system; system mode observes appearance changes. Neither writes backend/security settings.
- Existing native window resizing/ResizeObserver and keyboard/pointer sidebar resizing remain. Larger text triggers earlier automatic rail collapse; growing the window restores the saved width without rewriting the user's collapse preference. Settings tabs become a horizontal strip and rows wrap on narrow/short viewports. Context menus scroll within the viewport.
- Voice settings refresh existing native status probes when opened (status reads do not request permissions). Unknown native status does not imply availability. Dictation and tap-to-record/send spoken replies are distinguished; ambient listening/barge-in is explicitly unavailable. Permission prompts remain only in existing user-initiated native capture paths. Connection information is read-only application API origin and server-held token status; no login/token/endpoint editor was added.

### Focused verification and limits

TypeScript `tsc --noEmit`, theme guard and launcher zsh syntax passed. Focused DOM/state tests cover actual text-size changes, persistence, sidebar collapse/restoration, capability gating, protected identities, seen-route request shape, native status mapping, menu behavior and clipboard failures. Python checks verify capability projection without identity mutation and removal of the stale launcher override. Three canonical UI-serving tests exercise real handler output for built UI, missing build and forbidden legacy fallback, without starting a server.

Focused verification is performed from an external source snapshot with existing matching dependencies; source is not installed or packaged. No broad suite repeated under this bounded authorization. Source evidence: `core/agent_registry/registry.py`, `ui/src/api/{agentActions,gateway}.ts`, `ui/src/agents/AgentContextMenu.tsx`, `ui/src/App.tsx`, `ui/src/settings/{SettingsDialog,textSize}.ts*`, `ui/src/shell/AppShell.tsx`, and native `VoiceController.swift::micStatus` (read-only status versus explicit mic-start permission request).

Final focused results: 30 UI tests (29 action/settings/layout/status tests plus clipboard failure test), three capability/handler Python tests, and three canonical-serving tests passed. No application, service, HTTP listener or capture device was started by these checks. Evidence logs: `/Users/matthewjenkins/.cache/jaeger/verification/mac-agent-settings-20261019-160556`.

**Status: source verified only; live acceptance pending.** New controls are not in the running old app or the previously built UI artifact. Real right-click/keyboard behavior, native clipboard, OS theme changes, window/text sizing, microphone/TTS permissions and server-seen persistence across live clients still require coordinated runtime migration and visible acceptance. No Grok parity or feature-completion claim follows from test counts.

Remaining gaps: backend-supported rename/delete/duplicate/hide/sections/template mutations do not exist; no fake controls provided. Device-local pins are not cross-device server pins. Ambient/barge-in, camera/video/old avatar presentation and public share presentation remain unavailable as recorded in cleanup. Connection editing/security controls remain deliberately outside this scope. Agent delegation/background/resume behavior beyond existing home/history selection is unchanged and not qualified here. Runtime blockers remain old app PID 59466, test Gateway PID 8931/worktree, and the absent 8790 listener observed at cleanup; no runtime action was taken in this checkpoint.

## Historical checkpoints below — superseded implementations, not current acceptance

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
