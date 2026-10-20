# Mac app integration and completion

## Authorized runtime follow-through — 2026-10-19

### Live outcome and exact boundary

**Running:** native shell PID **4604**, `/Users/matthewjenkins/.cache/jaeger/verification/lifecycle-startup-20261019/native-shell/JaegerShell.app`, build **0.13.0+07cc9aa1**. Native source is unchanged by the later shared-UI fixes. Shared UI is separately served from `~/.cache/jaeger/ui-rebuild-mainscreen/dist`, latest functional source **5d9dc0b4**. The running shell's older build stamp is not evidence that its dynamically fetched UI is old; conversely its bundled full-source fingerprint predates those UI fixes and must not be presented as an all-components current artifact.

**Gateway:** PID **4623**, `http://127.0.0.1:33418/health`, canonical `core/gateway/server.py`, existing operator SQLite store and instance root. Started only the exact existing Gateway launch job after the live shell acquired ownership; no `stack up`, launchd-owner override or lease deletion. Backend code loaded at `07cc9aa1` and is unchanged by subsequent UI commits. Its health commit is a current checkout lookup, not proof of a hot reload. One existing `execution_unknown` request remains unchanged and was not replayed. Final sustained sample: **1,485 seconds** uptime; legitimate `menubar` heartbeat PID4604 age **1.8 seconds**, comfortably beyond the 15-second shutdown grace. Global Stop remained released and unchanged; Stop protection was exercised only in isolated tests.

**WebUI:** PID **6257**, `http://127.0.0.1:8790/?host=macos`, canonical backend. Its prior PID98906 had an environment override selecting the earlier agent-management snapshot. On the scoped restart, the existing managed job relaunched the canonical-default server. A redundant foreground replacement attempt PID6283 refused the occupied port and exited; no second listener survived. No job plist was edited. The final served HTML equals the current canonical build byte-for-byte (SHA256 `93aad874dfb8154386f245f37e54ce1d35c98b45dc16de70566d71d4e7c9db42`). State homes stayed `~/.jaeger/webui-agent` and `~/.jaeger/hermes-webui-state`. No new credential, permission, network bind policy, tunnel or old frontend was introduced. Existing unrelated jobs were not restarted.

| Area | Current qualification | Concrete evidence and limit |
| --- | --- | --- |
| Lifecycle | working-current | Explicit owner beat before Gateway startup; both required listeners sustained; 13 isolated ownership/Stop/lease checks pass. |
| Agent context actions | partial | Native right-click exposes profile, history, rename, read, pin and archive. Profile/history opened. Fixture rename submitted normally and shared pin appeared immediately and persisted across reload. A second owned fixture passed real backend rename/archive/restore and pin round-trip with immutable identity/metadata preserved. Native archive/restore UI still awaits acceptance. Primary remains protected. |
| Settings/text sizing | working-current for tested controls | Native General/Agents/Voice/Connection opened. Text 14px → 18px, persisted after reload, restored to14px. Connection shows real API origin/server-held token. Grok General has additional accent/language/system/bot-review groupings; Jaeger is not settings-complete. |
| Window/sidebar responsiveness | partial | Native zoom changed window size while content/composer remained reachable; original size restored. Narrow-window and sidebar keyboard/drag behavior were not independently qualified by the native automation attempts. Source checks from prior checkpoint cover responsive collapse; not substituted for live proof. |
| Conversation identity/history | working-current for tested paths | Existing primary transcript and Everyday's older history loaded. Fixture home remained the same `agent-native:mac-acceptance-20261019` across reload; saved reply returned. Reproduced and fixed home-page agent-ID omission (`dfcc8b3e`); native fixture header and composer now show the alias without changing immutable ID. |
| Streaming/final answer | partial | Real fixture no-tools turn completed with `MAC-CONTINUITY-OK` in durable storage. It exposed blank live output because text-only execution sent empty delta plus terminal output. Fixed missing terminal answer/matching-suffix projection (`60be4b2c`), duplicate protection checks pass and current UI serves it. Saved reply visibly returns after reload. Fresh post-fix controlled native live-answer retest remains pending. Tested specialist lane was text-only; no token-stream parity claim. Divergent provisional-vs-final answer replacement remains unqualified. |
| Stop | partial | Native Stop sent cancellation for only the fixture; durable request progressed `cancelling` → `cancelled`. Reproduced premature UI settlement and fixed it (`5d9dc0b4`): one cancel request, keep following the original request until terminal confirmation; pre-admission cancellation does not resubmit. 13 focused follow/Stop tests pass. Post-fix native live retest pending. |
| Approvals | partial | Real owned-fixture handoff approval created and denied through existing authenticated API; handoff became denied with no child run. No worker or external recipient was messaged. Active-turn UI card wiring exists; actual native decision and reload recovery were not qualified. Shared UI has no pending-approval-list consumption despite backend `GET /v1/approvals`; reload-safe/global approval visibility remains a specific source gap. |
| Tasks/boards/skills/tools | partial | Native Tasks control exists; real proxy/Gateway returns73 task records. Agent profile showed real handbook skill. Historical tool/delegation renderings loaded. No new tool execution, board mutation or task-worker dispatch was used as proof in this pass. Their live mutation workflows remain unqualified. |
| Voice/avatar | partial / missing | Native `mic.status` and `tts.status` probes report available; corresponding controls/settings visible. No capture, OS permission change or speech output test performed. Ambient/barge-in, camera and full avatar presentation remain missing, labeled rather than simulated. Idle agent avatars render; that does not qualify voice/avatar integration. |
| Gateway model editing | missing in current shared UI | Connection is read-only and WebHost model list remains empty. Existing backend runtime-model capability does not constitute a working frontend model/settings selector. |
| Grok comparison | observed UI only | Already-open Grok right-click has Pin, sections, unread, rename, copy conversation ID, hide and delete. General settings/voice entrypoints inspected read-only. Jaeger covers some analogous workflows with its own backend and intentionally has no destructive delete. Visual similarity and partial functional overlap are not full parity. No Grok remote backend behavior inferred, private transcript copied, or Grok message sent. Existing REA/Grok analysis reused; no additional broad REA run. |

**Focused checks/builds:** isolated lifecycle13; backend startup no-replay1; home/session UI20; final stream/Stop UI13. Earlier terminal11 are included in the final13, not additional independent proof. Shared UI was rebuilt only after reproduced source changes; type/theme/no-mock build checks passed. Native build/sign verification passed before launch. Existing VoiceController Sendable and UI chunk-size warnings remain. No broad suite repeated. Repo is clean after explicit commits. Evidence files are under `~/.cache/jaeger/verification/lifecycle-startup-20261019` (`live-health-first.json`, `live-health-final.json`, `live-controls-backend.json`, build/test logs).

**Current interruption to visible testing:** Matthew began using the native acceptance chat and left an unsent draft. It is now operator work, not disposable test data: its history, draft, alias and pin were left untouched. A coordination question is pending. Browser fallback could not run (`iab` unavailable); no browser/tunnel/access setup attempted. The separate controls fixture `native:mac-controls-20261019` is reversibly archived after restoring original pins and denying its only approval. No permanent deletion. No paused coder/worker resumed.

**Next action:** once the native window is available, preserve the draft and retest the served Stop/terminal fixes there, then verify archive/restore, Tasks and approval UI in owned fixtures. Only then claim those workflows live-qualified. If a new native artifact/relaunch is needed, build from the final source into an external non-running location and coordinate draft-safe shell replacement; do not overwrite the running bundle or blindly abandon its ownership heartbeat. Remaining source work priorities: reload-safe approvals, real model control, qualified native tool/board mutations, then voice/avatar capabilities. No full feature completion/parity claim.


Sole coder/runtime owner. Matthew now authorizes required local Gateway33418/WebUI8790 and current newer shell replacement, plus safe visible comparison with open Grok. No old fallback, unrelated workers, credentials/permissions/network changes, or unknown-outcome replay. Startup inspection reproduced a redispatch path for `execution_unknown` despite no proof of effect outcome. Removed automatic redispatch; startup now reports preserved unknown rows for explicit reconciliation. An isolated regression verifies request/history immutability and no scheduled execution. Earlier source-only restrictions below are historical. Live Stop testing also reproduced premature client cancellation: the client aborted its event reader while Gateway still reported `cancelling`. `WebHost` now submits one cancellation and keeps observing the same request until the Gateway terminal event, including Stop-before-admission; request failures are shown rather than claimed cancelled. Thirteen focused follow/Stop checks passed; live retest follows. A real fixture turn then reproduced a blank live reply: text-only execution supplies `turn.finish.output` with an empty delta. The follow adapter now supplies a missing terminal answer or matching suffix without duplicating already streamed content. It does not replay the turn. Eleven focused stream/reconnect/terminal-output tests passed; live retest follows. Live results will be appended after verification. Visible fixture testing reproduced a typed-adapter identity omission: home message pages had no agent ID and specialist chats displayed the lead name. `contractHome.page` now retains the canonical home binding and resolves explicit worker/history session identity from the existing session endpoint; it does not derive identity from a display alias. Focused contract/UI regression results and live retest are recorded below.

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


## 2026-10-19 — sidebar and primary source checkpoint (not deployed)

- Durable operator presentation-primary pointer defaults to the existing execution
  lead. Admin-scoped validated compare-and-set selects an existing eligible native
  lead/specialist and pins it atomically; stale pointers/full pins fail without
  partial updates. Registry execution roles/configuration, tools, permissions,
  immutable identities, sessions and history are not transferred or rewritten.
- Shared UI supplies Pin/Unpin, Mark as Unread, Copy conversation ID, Hide from
  sidebar and primary replacement picker; nonprimary Make primary is reachable.
  Copy resolves the selected session or backend home ID, never the agent ID.
  Rename/profile/history/restore remain in management. Hiding primary retains its
  pointer; unpinning retains primary and moves its row out of the pinned strip.
- Explicit unread survives storage reopen and overrides local seen state until
  explicit open/read. Polling does not clear it. Changing primary preserves the
  currently open chat/draft; remount defaults to the persisted primary.
- Fixed popup coordinator so clicking an alert-dialog rename input does not dismiss
  it. The remaining primary-flow failure was a test-contract error: the pinned
  container may disappear entirely after unpin. Assertion now accepts absence and
  additionally proves the agent remains in the sidebar; clipboard mock is restored.
- Final focused evidence: external `~/.cache/jaeger/verification/agent-primary-20261019/`:
  `ui-tests.log` 23 passed (7 files); `primary-flow.log` 2 passed;
  `typecheck.log` passed; `ui-build.log` passed (Vite chunk-size advisory only).
  External build: `ui-source/dist`, unserved. `backend-tests.log` 20 passed (final rerun after UI edits).
- Isolated two-agent fixtures cover primary persistence/reopen, CAS/pin conflicts,
  ineligible agents/admin scope, unchanged execution/history, unread, exact home ID,
  draft continuity, hide/restore and pin/unpin. These are source/contract evidence,
  not native acceptance or Grok remote-backend parity.
- Matthew's “Wait while I use it” remains binding: no native window/draft access,
  production mutation, service restart/reload, deployment or served-build switch.
  Live popup appearance/clipboard, cross-client persistence and native acceptance
  remain pending. Earlier Stop/answer/approval/voice limits remain unchanged.


## 2026-10-19 — authorized rollout blocked before runtime change

Matthew superseded the earlier wait and authorized scoped deployment. Inspection
confirmed existing shell PID4604, Gateway4623 and WebUI6257; exact managed jobs
remain `com.jenkinsrobotics.jaeger-gateway` and `com.jenkinsrobotics.jaeger-webui`,
canonical repo working directories, loopback33418/8790. Both health URLs returned
200. No job configuration, listener, credentials or user metadata changed.

Replacement built and signature-verified externally at
`~/.cache/jaeger/verification/agent-primary-20261019/native-shell/JaegerShell.app`,
version `0.13.0+11272d91`, source commit
`11272d91dd2c584b8fbc7259c83ac7698457acae`, source fingerprint
`391d7c3e85fe1b9258e97a7a129055d9b5a1c56609959c980b0e2789b34aac4f`.
The passing shared UI candidate remains unserved in `ui-source/dist` alongside
the bundle. Build log: `shell-build.log`; detailed snapshot: `deployment-blocker.json`.

Concrete blocker: the old shell remains alive despite its window being closed.
Three desktop access attempts (exact running bundle path twice, then app name)
timed out. `MinimalChat.tsx` holds draft text only in React memory; a closed window
is not proof of an empty draft. Cannot safely relaunch/reload before confirming
or recovering any retained draft. No shell quit/start, Gateway/WebUI restart,
served-build switch or live-agent mutation was performed. New routes, new native
menu/picker and sustained replacement ownership remain unverified live. Next:
recover/check the old window draft, then perform the already-authorized coordinated
shell ownership replacement and exact managed-service reloads.


## 2026-10-19 — fixed sidebar/primary rollout running

Supersedes the draft-access blocker above. Matthew supplied fresh read-only UI
evidence: current composer empty, no attachments, REA plan already sent; the
composer has one in-memory draft, not a hidden per-chat draft store. Existing
local binding was unavailable in this tool session, but this evidence supported
coordinated replacement without submitting/discarding text.

- Built/signature-verified newer shell externally; running bundle
  `~/.cache/jaeger/verification/agent-primary-20261019/native-shell/JaegerShell.app`,
  **0.13.0+3a347be8**, commit `3a347be8976a44de640097aca3a874bef37f4fb4`
  (includes feature commit `11272d91`; later change was documentation only).
  Source fingerprint remains
  `391d7c3e85fe1b9258e97a7a129055d9b5a1c56609959c980b0e2789b34aac4f`.
- Exact old shell4604 terminated; old bundle preserved. Waited for its real last
  heartbeat to age beyond grace, then launched **PID12591** using supported
  `--own-production-lifecycle`, explicit production state and lease opt-in.
  Legitimate heartbeat acquired before exact managed Gateway/WebUI job reloads.
  No lease deletion/forgery, owner override, Global Stop change or job edit.
- **Gateway12599**, loopback `http://127.0.0.1:33418`; **WebUI12608**,
  loopback `http://127.0.0.1:8790`. Both healthy after over 100 seconds;
  heartbeat owner menubar/PID12591, sampled age1.33 seconds.
- Authenticated primary GET200, new primary invalid-body validation400, new
  advertised primary/unread capabilities present. Existing auth rejects unauthenticated
  primary POST401; WebUI authenticated proxy reaches new primary validation400.
  Nonexistent owned-namespace seen request returns structured404 without writing.
- Served native-origin HTML matches candidate exactly; both JS and CSS assets
  match candidate hashes. JS `index-CxQLOkm3.js` SHA256
  `3dec7ea6cc7220c9d69565f4caeb0f680c8e466f8ba287e78af7d15686de5990`;
  all hashes, process commands, source fingerprint and route checks in external
  `runtime-verification.json`; build logs and passing scoped source logs retained.
  Prior served dist preserved under external cache `previous/primary-rollout-*`.
- Native window initially loaded during service restart and showed connection
  failure; after listeners were healthy, one authorized Cmd-R loaded the fixed UI.
  Visible empty composer, retained sent transcript, Jaeger Primary badge.
  Primary popup: Pin / Mark as Unread / Copy conversation ID / Hide from sidebar /
  Replace with different Bot. Picker: Choose a primary Bot, existing candidate
  selector and disabled Make primary until selection; cancelled without submission.
  Builder popup additionally proves nonprimary Make primary; dismissed unchanged.
- No real-agent primary/pin/hide/explicit-unread action submitted. Normal opening
  of Jaeger updates its read marker (observed sole recent agent.updated payload:
  native:jaeger read_marker); aggregate metadata hash therefore changed and is
  NOT claimed byte-identical. Existing execution_unknown row hash unchanged,
  startup explicitly preserves it without replay; Global Stop file hash unchanged.
- No credentials, network/auth policy, unrelated service configuration or old
  fallback changed. New bundle left open. This proves scoped rollout/menu/picker,
  not full Grok parity, live primary mutation/cross-device persistence, successful
  model turn, Stop/approval or voice acceptance. Those earlier limits remain.


## 2026-10-19 — live popup comparison and bounded correction

Live AX: Grok primary in Pinned Bots offers Unpin, Mark as Unread, Copy conversation
ID, Hide from sidebar, Replace with different Bot. Jaeger primary is currently
unpinned (in specialist list): Pin is correct, not a label defect. Its same primary
action order is present. Grok ordinary unpinned Jaeger Mac App offers Pin, Move to
new section, Mark as Unread, Rename Bot, Copy conversation ID, Hide from sidebar,
Delete. Jaeger supports rename but had omitted it from this popup; now exposed for
ordinary agents with advertised rename capability. Unsupported sections/destructive
delete remain absent; Jaeger Make primary remains reachable by design. No real bot
state changed for comparison. No ordinary pinned Grok bot exists in the observed
sidebar; primary-unpinned Grok and primary-pinned Jaeger states were not created
by mutating user agents. Pin state permutations remain covered by isolated tests.

Jaeger live screenshot reproduced wrapping Replace with different Bot and a hover
highlight stopping before the row edge. Producer: fixed 242px inner stack under a
310px outer positioning box, plus nested wrappers with intrinsically sized buttons.
Desktop popup now sizes to longest label within viewport, rows span full width,
and labels stay single-line. Phone preview geometry unchanged. Original local SVG
swap arrows replace the incorrect back-arrow icon; existing shipped REA TD component
at offset469000 names arrow-swap. Replacement also requires advertised primary
capability, not only a caller-provided alternative flag.

Grok native screenshots returned a tiny distorted whole-window image even after
settled capture/raise; live AX labels are readable, but exact Grok pixel width,
padding, icons, separators, hover and placement cannot be visually certified.
Jaeger separators remain two groups before copy and hide, as requested primary
reference; no speculative radius/placement/style rewrite made. Grok's existing
composer draft retained; no message, account setting, pin/read/hide/primary action
submitted in either app.

Focused popup, primary and management-flow tests:7 passed (3 files), production
UI build/typecheck/theme/no-mock passed; Vite size advisory remains. Logs external:
`agent-primary-20261019/popup-comparison-tests.log` and
`popup-comparison-build.log`. UI-only deployment/visible retest recorded next.


**Popup live retest:** Shared UI feature commit
`9f1082a25df75734212717d8f22cbacb9b9677b3` deployed via external dist only;
old distribution preserved in `previous/popup-compare-1792458114`. Native shell
12591/build0.13.0+3a347be8, Gateway12599 and WebUI12608 stayed running; no service
restart or native bundle replacement needed. Empty composer observed before
authorized Cmd-R. Native screenshot proves replacement label single-line, hover
full width, two separators and original swap icon. Live AX proves unchanged
primary order and new ordinary Rename Bot action; picker opened then Cancel,
ordinary menu dismissed. No primary/pin/hide/unread/rename action submitted.

Served HTML/all referenced JS/CSS match passing candidate exactly. Main JS
`index-z3zwKTGI.js` SHA256
`ad69147b4f87a2183587d88aa648613151a9af69b3023bd28ef075f8789f0193`;
CSS `index-DPkosDT4.css` SHA256
`ac5cfa079175a16fe585f2c61c23034549d39d16db09a7191e87efa1b26ad00e`.
Both health endpoints200; legitimate PID12591 heartbeat age0.90s. Evidence external
`popup-live-verification.json`. Pixel-level Grok width/padding/hover/placement
comparison still blocked by distorted234px capture; no exact parity claim.
No new backend code, permission changes, runtime authority or conversation
navigation changes. Backend20 passing from feature checkpoint remains source
evidence, not a newly rerun suite in this UI-only correction.


## 2026-10-19 — duplicate shell resolved; correct-owner UI acceptance blocked

New process/window inspection proves stale PID12099 at
`verification/mac-agent-management-20261019-163701/native-shell/JaegerShell.app`
owned Jaeger window17202, while intended lifecycle owner12591 at
`verification/agent-primary-20261019/native-shell/JaegerShell.app` owned window17223.
Same bundle ID/title did not establish UI process identity. Earlier live popup
captures could have targeted12099: they prove shared-UI rendering in a shell,
NOT confirmed rendering by12591. This qualifies earlier process-attributed claims.

Matthew supplied fresh stale-instance empty composer/no attachments observation;
no draft interaction followed. Verified exact12099 executable then sent SIGTERM
only to12099. It exited; only12591 remains. Bundle files retained. Owner12591,
Gateway12599 and WebUI12608 unchanged; heartbeat remains menubar/PID12591, age1.71s.
No lease action, service restart, app relaunch, real-agent action or unknown replay.
Both health endpoints200; HTML/JS/CSS still match9f1082a2 candidate hashes; unknown
request row hash unchanged. External `duplicate-instance-resolution.json`.

Precise remaining blocker: CUA exact intended bundle-path lookup times out even
after clearing this tool session's stale bindings. Direct verified window17223
targeting is rejected as unsupported on macOS. No ambiguous name/bundle-ID lookup
used. Final window-server read reports12591/window17223 exists but is not onscreen.
Cannot show that window or harmlessly retest its popup through current permitted
UI tool. Do not claim correct-owner loaded9f1082a2 pixels, focus or hover acceptance.
No restart workaround attempted: explicit latest scope leaves12591 untouched.
Next action: recover exact12591 window access/show (without launching a duplicate),
then verify its loaded popup. Source fixes and served hashes remain verified.


## 2026-10-19 — corrective primary badge / desktop popup (acceptance incomplete)

Matthew rejected previous presentation; similar labels/tests are not acceptance.
Producer defects: SupervisorArt hid star when unread; only pinned tiles had a
star; role-lead fallback and unpinned text label substituted for primary identity.
Desktop still inherited phone blur/22px corners/large spacing. Read/unread always
used envelope/Mark as Unread; unpin used unslashed pin. Ordinary menu added a
nonreference Make primary control. These source defects are corrected.

Authoritative state chain: existing SQLite schema_meta agent_primary:operator →
GatewaySessionStore.primary_agent_id → server._with_skills/project(primary_id),
with one pointer snapshot per catalog → GatewayClient.agents typed Agent.primary →
useAgentsStore → sidebarRows/AgentAvatar + ChatPane mounted agents projection →
header/menu branches. No role/name/index/pin fallback selects badge. Exactly one
primary projection permitted; invalid multiple-primary snapshots fail visibly,
preserving last roster. Refresh generation ignores delayed older fetches; an
agent.updated event invalidates in-flight data before debounced authoritative
refresh. Poll/remount refresh covers dropped-stream recovery. No optimistic
primary switch: backend setPrimary CAS must succeed; rejected saves keep old
star/menu/pointer. No auth, roles, history, config or backend mutation changes.

Original reusable avatar corner badge now shown in row/tile/header for projected
primary; unread remains independently visible. Original star graphic; REA
rendering main corner at index-wlkGG389.js~264142 uses filled star; Kbe/Xbe at
256944–257028 defines16px pinned/9.6px expanded badge,8px/4.8px star. Shipped CSS
sand-19arc22/qxvkua/xcaa6e resolves yellow-bright #f59312, white star, inset border.
Our new token matches yellow/white; small header marker scales independently.

REA Ly~460600 verifies bell vs bell-dot and Mark as Read/Unread state inversion;
By~461460 pin-slash vs pin; rename pencil-square; copy, eye-slash and arrow-swap
confirmed callsites. Local original outline glyphs implement those semantics.
Shipped CSS menu variables:30px row,13px type,18px line,12px outer/6px row radius,
6px inner/8px row inset. Desktop uses these with existing font-size preference
scaling, two primary separators, single-line full hit/hover rows, cursor alignment
with viewport clamp; full-page phone blur removed only for desktop agent popup.
Ordinary Rename Bot advertised; Make primary remains in Settings/Agents, absent
from context menu. Sections/delete unsupported and absent, not fake controls.

Changed source: agents/AgentAvatar, SupervisorTile, AgentRow, AgentsSidebar,
agentsLogic, agentsStore, AgentContextMenu, agents.css; App; chat/ChatPane,
mountMinimal, host typed mount update, MinimalChat; shell/tokens.jaeger.css.
Widget roster updates in place so header primary can change without remounting
composer/draft. Updated avatars/menu/primaryFlow tests; new primaryOrdering test.

Final focused UI23 passed (6 files); backend20 passed; production build including
type/theme/no-mock passed (existing Vite chunk advisory). External evidence root
`agent-primary-20261019`: primary-correction-tests.log, -backend.log, -build.log.
Two-specialist fixture moves primary and sole represented star identity; old
loses star/Replace, retains chat/draft/role; unread/star, pin/unpin, hide/restore,
reopen, rejected save, exact copy covered. Separate delayed-response fixture
proves stale A cannot overwrite newer B, alias/order/lead role cannot choose star,
invalid multiple primary rejected. Existing backend fixtures assert SQLite reopen,
CAS/full-pin atomicity, unchanged histories/tools/execution roles/admin scopes.

LIVE: Grok primary pinned/read still Unpin/Mark as Unread/copy/hide/Replace;
ordinary unread currently Mark as Read/Rename Bot etc, confirming inverse.
Reference screenshots still distorted234px; cannot certify row/icon/hover pixels.
Grok drafts untouched; menus dismissed only. Correct sole PID12591 exact-path
CUA still times out. Tried registered ctrl-option-space without launching any
app: native log confirms existing window toggles, but exact owner AX capture
remains unavailable. Requested operator show existing window asynchronously; no
answer yet. No native reload/relaunch/service restart, no real-agent actions.
Do NOT claim correct-owner visual acceptance. Serving passing candidate is safe
without reloading a hidden potentially-drafted window; hashes recorded separately.


**Served corrective checkpoint:** feature/source commit
`32a73e9555272c8bca760ad603c788a2b58fe852`; external candidate served without
service restart or native reload. HTML and referenced assets byte-match build.
JS index-BkVTmgXu.js SHA256
`bfdb74649553ace3d27646b38d84fcec4ad86ac9ac5180f7c6e9f963ea5de634`;
CSS index-Bc8iuwag.css SHA256
`e51228eb01791e209419ea7695967e926d1735ac5f596ddd875bcd2e843c141c`.
Full manifest `primary-correction-deployed.json` beside focused logs. Only shell
12591 remains; Gateway12599/WebUI12608 unchanged, health200, legitimate heartbeat
age0.11s; unknown request hash unchanged. Old served dist retained under
`previous/primary-correction-1792458933/dist`. NOT native acceptance: cannot assert
that12591 has loaded these new bytes or that every visual row/icon matches Grok.
Exact owner AX access and readable reference/current capture remain the concrete
blockers. Operator window-show question remains unanswered. No new worker/credential,
real primary/pin/unread mutation, draft submission or lease manipulation.


## 2026-10-19 — bounded continuity, exchange follow-up and small icons

Scope: voice/camera/video/large-avatar work paused. Existing popup32a73e95 and
evidenceb57bb845 retained; correct-owner native visual acceptance still blocked.
Plan derived from canonical code, not Grok backend assumptions: home-session
contract/paged inline history already exists; TaskOwner/handoffs and typed message
rows own progress/results; AgentMessages bridge is caller-scoped inert data.
Reuse these, no new identity/session/runtime/message authority. REA analysis and
inventory under Documents/Codex/2026-10-19/task provide client reference only.
Grok inline history and setMainAgent+pin do not imply client history transfer.

Implemented slices:
- Validated icon_preset stored in existing agent_presentation:operator. Backend
  advertises original robot/robot-square/robot-shield choices; Settings/Agents
  selects/restores original avatar through existing admin/profile-protected PATCH.
  Registry ID, role, grants, context, primary/pin/unread independent. Sidebar and
  header consume same acknowledged projection; no real-agent icon changed in tests.
- Task queued/handoff admitted/approved project to queued, not working. Row exposes
  actual state. Only thinking/streaming/executing states can animate small icons;
  waiting/blocked/idle/error/queued and historical handoff/results remain static.
  Reduced motion retained. Empty pending turn says Waiting for progress and has
  no running icon; tool motion uses typed executing state, not guessed running.
- Existing message status now survives durable API projection and home-page
  adapter; task result status persisted alongside its row. Home result entries
  preserve origin conversation, root thread and reply-to handoff IDs. Inline
  older-history paging retained; no session navigator introduced. Handoff transcript
  delivery uses existing background_deliveries receipts/atomic store to dedupe
  repeated delivery and preserve existing pre-upgrade posts; conflicting text
  fails for reconciliation rather than silently overwriting history.
- POST /v1/handoffs/{id}/reply + existing WebUI proxy, typed adapter and inline
  Follow up dialog. This is an explicit operator-requested follow-up, not forged
  autonomous peer chat. Same canonical participants/conversation/project/workspace,
  same tool ceiling, earlier task/result as permitted exchange data; stable new
  request ID and durable reply/root correlation. Reuses normal handoff admission
  and ALWAYS creates a fresh approval, even when parent needed none/project has
  a standing handoff grant. Incoming bridge/message data cannot invoke this path.
  Active/unknown exchanges reject follow-up; no replay. Repeating the same request
  returns existing handoff; changed payload conflicts. UI reports only acknowledged
  pending-approval status and preserves draft/error on transport failure.

Focused verification: UI38 passed across8 files, including icon Settings wiring,
inline wire correlation, failed-send draft/stable-key retry, rejected primary and
ordering regression; production theme/type/no-mock build passed (size advisory).
Backend61 passed: real isolated REST follow-up202 pending approval, idempotency,
SQLite reopen/correlation/tools/registry/history unchanged; unknown/active403/409
protection, admin/prefixed scope, existing profile proxy guard, one-time posts,
small icon persistence and queued status. Isolated local fixtures only; no paid
model/provider, external agent, operator primary/unread/pin or credential mutation.
External logs: agent-primary-20261019/continuity-ui.log, continuity-backend.log,
continuity-build.log. Test fixes distinguish newly additive contract fields from
actual defects; receipt column assignment and proxy quote binding were repaired
before qualification. No broad suite used.

Runtime preflight: sole shell12591, Gateway12599/WebUI12608 exact canonical managed
jobs; fresh legitimate lease. Requests have no queued/running entries; durable
tasks have no queued/running entries. One existing execution_unknown request,
ten unknown handoffs and one pending handoff approval must remain unchanged.
Only required Gateway/WebUI reload and external dist switch authorized; native
window/draft will not be reloaded while exact-process access is unavailable.

Limits: follow-up is approved task exchange, not arbitrary native peer-to-peer
free-form messaging or an automatic reply engine; caller-scoped bridge semantics
unchanged. No claim of external bridge delivery or autonomous messaging parity.
Successful follow-up model execution/result roundtrip not exercised; only admission
and durable message/result fixtures. Native Settings/dialog/icon visuals and
correct-process popup acceptance remain unverified. Voice/media/large avatars
not implemented or tested in this pass. Runtime rollout evidence follows.


**Bounded rollout result:** source commit
`61f08ff71ce1363e91911b09b46eca460b1a1dcf`. Exact existing Gateway and WebUI
launch jobs reloaded after preflight; shell12591 and bundle0.13.0+3a347be8 unchanged.
New Gateway19707 on loopback33418 and WebUI19711 on loopback8790 healthy beyond
15s grace (over80s at final process sample), legitimate12591 heartbeat age1.72s.
New authenticated catalog exposes icon_choices/ui_actions.icon; direct and WebUI
proxy follow-up on nonexistent owned fixture returns409, unauthenticated route401.
No real handoff, icon, primary, unread or message mutation used for runtime checks.

Served HTML/JS/CSS match passing candidate byte-for-byte. JS index-DkqErgZz.js
SHA256 `8fb3f5b8fd6a31ef6f4aa69c6096ea2a1965b827185a0766dbb611e5e7da061e`;
CSS index-BijpUMNE.css SHA256
`9608489256be019316ad15e41b6797a3cdd0914fe42f3aa2f4700bc02a3b8518`.
Full external `continuity-runtime.json`; old dist preserved under
`previous/continuity-1792460841/dist`. One unknown client request hash/count
unchanged; all unknown/pending handoff rows, presentation/primary metadata and
Global Stop hash unchanged. Startup explicitly reports preserving unknown without
replay. No unrelated jobs, shell restart, launchd edit, network/token/auth changes.

Read-only exact12591 bundle-path CUA retry still timed out. No native reload or
draft interaction; cannot assert this window loaded new bytes or certify visible
Settings/icon/follow-up/popup behavior. Backend and serving-chain evidence is
current; native acceptance remains blocked. Automatic arbitrary peer inbox/replies,
external bridge roundtrip and successful new follow-up model/result execution
remain unimplemented/unverified as distinguished above. Voice/media and large
avatar scope remains paused, not removed or silently replaced.
