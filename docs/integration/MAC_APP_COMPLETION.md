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

## Correlated peer response closure — 2026-10-19

Prior61f08ff7 gap distinguished: native follow-up admission/result producers were
implemented, but a successful admitted child roundtrip had not been validated.
AgentMessages had no connection to those execution receipts; inbox messages were
inert. This pass adds explicit `source_message_id` binding through the existing
scoped goal admission, then automatic terminal responses to that exact message.
It does NOT interpret arbitrary incoming text as execution authority.

Source: agent_bridge routes/MCP accept the optional binding; service validates
participant-scoped `reply_to`, rejects client correlation; schema15 adds nullable
source ID plus unique caller/source index in the existing goal table. No old-row
backfill. responses.py derives answer/status only from canonical terminal receipts
and freezes model completion as unverified; result correlation includes goal,
request, session and canonical task/handoff IDs where present. Gateway terminal
producer delivers automatically; inbox/goal reads recover a crash gap using data
only. Deterministic IDs deduplicate message/outbox delivery. Task/question source
only, one goal/source, no response-triggered dispatch or approval bypass. Existing
workspace grants, admission, tools, scopes and identity/history remain intact.

Focused external peer-tests.log: **101 passed,85 existing aiohttp key warnings**.
Includes actual temporary native write through scripted local model transport,
owner approval (peer cannot approve), denial/no effect, second correlated follow-up,
duplicate binding/delivery, foreign access/reply rejection, server metadata spoof
rejection, unknown recovery/no replay, failed/blocked outcome status, migration
preservation/no backfill, and existing tool confinement/outbox transport checks.
Native handoff follow-up now demonstrates real approval → delegate runtime →
canonical child admission/receipt → correlated origin result. Only its local model
transport is scripted. Specialist registry/tool ceiling/history unchanged; repeated
terminal follow-up returns same handoff without another execution. Early test
failures were test-contract issues (unsupported synthetic receipt status blocked;
terminal idempotent response is200, not pending202), fixed to use real contracts.
No broad/UI suite or UI build needed; no UI source changed.

Read-only CUA inventory refreshed once: running apps list contains no Jaeger entry
or process-specific target. Prior exact-path lookup timeout/windowId unsupported
remains the native acceptance blocker. No repeated lookup, native input/reload,
duplicate app launch or draft access. Popup visual proof remains outstanding.
Voice/media/large avatars remain paused. External credential-backed peer delivery
and remote Grok semantics remain unverified; inbox data alone still intentionally
cannot start work. Approved execution uses existing explicit goal/handoff requests.

Rollout preflight: sole production shell12591, Gateway19707:33418 and WebUI19711:8790;
fresh legitimate lease, no active request/handoff, unknown request1 preserved.
Only exact Gateway launch-job reload is needed; no shell/WebUI/assets switch.
Runtime outcome and source commit recorded below after verification.

**Peer closure rollout:** source `0a0516433d15be66634aa0c101a8e2caab605d82`.
Reloaded ONLY existing Gateway launch job; PID21888 owns loopback33418. Initial
probe during startup was connection-refused; after startup health200 remained
healthy in two samples beyond15s grace. Existing WebUI19711:8790 and shell12591
(bundle0.13.0+3a347be8, exact agent-primary external path) were not restarted.
Legitimate menubar12591 heartbeat fresh throughout. Schema15 plus authenticated
invalid-source probe now returns Invalid identifier (old backend returned Invalid
goal fields): new contract actually loaded, not inferred from GitHEAD/health.
No valid real-agent goal/message was created. Tasks read returns no queued/running.

Before/after/stable hashes match for the one execution_unknown request, all
unknown/pending handoffs, presentation/primary and Global Stop. Nothing replayed.
Served existing shared UI assets still match external passing dist byte-for-byte
(index-DkqErgZz.js SHA2568fb3f5b8fd6a31ef6f4aa69c6096ea2a1965b827185a0766dbb611e5e7da061e;
index-BijpUMNE.css SHA2569608489256be019316ad15e41b6797a3cdd0914fe42f3aa2f4700bc02a3b8518).
External evidence: agent-primary-20261019/peer-tests.log, peer-before.json,
peer-preflight.json, peer-after.json, peer-stable.json, peer-contract-{before,after,stable}.json,
peer-runtime.json under ~/.cache/jaeger/verification. Other pre-existing test
Gateway/WebUI processes observed read-only, untouched; only33418 job reloaded.

Residual limits: no external peer/provider acceptance or Grok remote backend
claim; local model transport scripted. Arbitrary inbox text remains intentionally
inert until existing explicit scoped goal admission, then terminal reply is
automatic. Crash-gap recovery is on inbox/goal read, not a new autonomous worker.
No native messaging/popup/dialog visual acceptance: tool inventory lacks Jaeger,
known exact lookup unsupported/timed out; no native input/reload risking draft.
Existing unknown request remains unresolved, not retried. Voice/media remain paused.

Focused hygiene scan found two pre-existing ignored bytecode files:
jaeger_ai/__pycache__/__init__.cpython-312.pyc (mtime2026-10-18 10:20:36)
and dev/__pycache__/bytecode_guard.cpython-312-pytest-9.1.1.pyc
(mtime2026-10-17 20:58:58). Not produced by this pass; left untouched rather than
expanding into unrelated cleanup. Tracked working tree clean after evidence commit.

## Independent browser acceptance fixture — prepared, visual checks pending

Actual current shared UI served at http://127.0.0.1:58310/?host=macos through real
WebUI Handler/proxy and isolated Gateway http://127.0.0.1:58305, owned fixture
PID23345. Source remains0a051643; current served HTML/assets match passing dist.
No mock UI or mock adapter. Contract-worker pattern from
`dev/tests/fixtures/gateway_contract_worker.py`, external adapted worker only:
scripted OpenAIAdapter.call boundary, local lmstudio model config requiring no
API key, existing caller_tokens directory reused read-only, no generated tokens,
passwords, signing/PBKDF keys or authority grant files. Real admission, scopes,
approvals, session/task/handoff/presentation stores and SSE handlers remain.
No new bridge workspace grant or external peer/provider connection. Network
fixture guard admits only its own Gateway connection; no provider calls allowed.
Existing production lifecycle heartbeat and Global Stop guards remain in use,
read-only during these checks. Coordinator must not use Global Stop/auth controls.

Fixture state: ~/.jaeger/verification/browser-acceptance-20261019.
External runner/logs/manifest: ~/.cache/jaeger/verification/browser-acceptance-20261019.
Alpha: native:everyday / agent-native:everyday,130 explicitly SEEDED history
messages to exercise50-message paging. Beta: native:builder /
agent-native:builder, idle seeded context. Seeded parent browser-fixture-parent
links Alpha→Beta with read_file ceiling and a clearly labeled nonexecuted prior
result, for normal Follow up/approval UI. Small robot presets initialized through
normal presentation PATCH; fixture Settings/primary/pin/unread/hide mutations
allowed. Primary initially Alpha; read-only handoff sample now authoritative Beta
(after coordinator interaction); no reset of those fixture changes.

Important fixture limits, NOT acceptance claims: first launch exited because the
optional webhook default8793 was already occupied; nothing else stopped. Existing
JAEGER_TEST_HEADLESS=1 fixture mode excludes unrelated background producers. The
initial probe browser-fixture-ready-probe then stayed admitted without entering
the scripted provider. A single fixture-only restart preserved it as
execution_unknown, never replayed. Its cause has not been established; therefore
successful live browser working/streaming/follow-up execution remains unproven.
Owned fixture task inspection is saved locally for subsequent diagnostics. Prior
successful isolated101-test results remain separate from this browser attempt.
Do not infer genuine working motion from this unresolved fixture request.

Earlier URL58091 retired at fixture-only restart;58310 is stable and left running
for coordinator. No more fixture restart/reseed while visual checks proceed.
Production shell12591/Gateway21888/WebUI19711 untouched. Before/after hashes for
production unknown request1, unknown/pending handoffs, agent presentation/primary
and Global Stop match; legitimate shell12591 heartbeat fresh. No native window
interaction or draft access. Native12591 acceptance remains separate and blocked.
No successful suites rerun; only local serving/hash/auth/data/probe checks.

## Browser fixture transport repair and receipt-backed motion — 2026-10-19

Coordinator Safari AX checkpoint on former58091: older history060→001 loaded
inline, no session list. Alpha Settings robot→robot-shield survived Cmd-R and
reopening Agents. Beta primary replacement persisted, sole AX Primary bot marker
and Replace branch moved from Alpha while Alpha chat remained selected. Primary
popup: Unpin / Mark as Read / Copy conversation ID / Hide / Replace; ordinary
Alpha: Unpin / Mark as Unread / Rename / Copy / Hide. These are coordinator-reported
live browser observations, separate from native12591. Distorted tiny screenshots
still prevent pixel/star-color/separator visual proof. Safari AX and app screenshot
APIs available; no full-desktop capture API exposed. capture_screen_context is
voice-only and is NOT a fallback. Missing native target binding does not mean the
Mac is disconnected; native12591 remains running.

Disconnect:58091 retired during the earlier fixture-only restart. Stable repaired
fixture uses58310(WebUI)/58305(Gateway). Diagnosed execution through the owned
async task snapshot: ImportError importing bind_skill_scope from installed
~/.jaeger/venv/lib/python3.12/site-packages/jaeger_agent/skill_registry/playbook_skills.py.
Canonical packages/jaeger-agent has that API. Fixture launcher now explicitly
loads canonical packages/jaeger-agent and packages/jaeger-os on PYTHONPATH; no
install, dependency rewrite, credentials/grants or production runtime change.
Preserved both prior diagnostic receipts; neither replayed. Distinct probe3
completed via owner-react with output BROWSER-TRANSPORT-PROBE-3. Separate approved
follow-up browser-repaired-followup-check completed on its native child session,
same browser-fixture-parent thread, read_file ceiling, and origin transcript post.
Coordinator's earlier pending follow-up approval was not resolved by these checks.
A distinct30s scripted-provider background stream completed after request closure
with durable origin result (Completed after301 chunks). No real provider/peer.

That live stream exposed an actual projection defect: active chat receipt was
running but agent summary idle because only tasks/handoffs were considered.
Narrow producer fix: summary joins active durable receipts to agent-owned session
IDs. Running→working, admitted/queued→queued, awaiting approval→waiting_approval,
cancelling→blocked. Terminal/unknown history does not fabricate current running
motion. Existing status priority and handoff/task semantics unchanged. No new
execution, grants, state table or UI assets. Source changed only agent_summary.py,
summary route, and focused contract checks. Production process stays on its
previous loaded backend; this repair is loaded ONLY into isolated fixture.

Focused25 tests passed,10 existing aiohttp warnings, exit0. First run's25 assertions
passed but isolation guard correctly rejected concurrent fixture monitor writes;
fixture was paused, same focused file rerun with guard intact and passed.
No broad/expensive successful suite repeated. External summary-focused.log,
repair-running.json and repair-qualified.json retain source/test/runtime separation.
Fixture restart and post-fix running→idle evidence follow below.

**Fixture repair qualified:** source `d2e96265`, isolated PID24286, fixed loopback
WebUI58310/Gateway58305 healthy in repeated checks beyond lifecycle grace. URL
http://127.0.0.1:58310/?host=macos is left stable; old58091 remains retired.
Canonical package-path repair eliminates observed bind_skill_scope import failure.
New browser-postfix-background-check: receipt running + summary working during
real30s scripted-provider wait, then completed persisted transcript + summary idle.
Saved postfix-running.json/postfix-qualified.json. Separate prior approved child
handoff_12d63e7c7a3a completed and posted to browser-fixture-parent thread; worker
session and result match. No live browser-motion visual acceptance claimed yet.
Both original diagnostic receipts remain execution_unknown unchanged, not replayed;
Beta's home keeps its unknown history/guard. Use Alpha for a fresh SLOW-STREAM chat
check; navigate away/back to observe background completion. For Beta working
motion, use normal Follow up with SLOW-STREAM and its owner approval, then inspect
correlated child/result. Coordinator's previously pending approval is preserved.

Alpha shield preset, Beta primary, all fixture presentation/history/approvals
preserved across repair. Manifest updated; external launch.py resumes only fixed
owned ports and canonical package paths, refuses an occupied port. No production
restart/install/deploy, source dependency environment change, credential creation,
grant change, native input/reload or unknown replay. Production shell12591,
Gateway21888/WebUI19711 untouched; protected-state hashes still match pre-fixture
baseline and legitimate12591 heartbeat fresh. Source working-state fix is NOT yet
loaded into production Gateway21888. Source and fixture backend evidence are now
current; coordinator visual checks are the next action. Voice/media remain paused.

## Standalone follow-up approval visibility repair — 2026-10-19

Fresh coordinator Safari58310 evidence: Beta primary persisted; a unique composer
submission rejected by the preserved unknown reconciliation guard, not retried.
Alpha Follow up submitted once; saved pending handoff_de3ba2e52f16 /
approval_256248f9a08f for exact task "Isolated browser follow-up acceptance: return a
short correlated result." No visible decision card; no unsent browser draft.

Inspected durable records: still pending, no execution. Two producer/adapter gaps:
standalone handoff approvals omitted session_id; home live stream handled posts,
not standalone approval recovery outside an active turn. Repair binds new
approvals to saved origin_session. Existing unbound rows are enriched read-only
from metadata.handoff_id→durable handoff (session/task), with no row rewrite.
Existing GET approvals?session_id filtering reused; WebUI now preserves that query.
Typed adapter exposes optional pendingApprovals; inline SessionApprovals after
latest transcript restores/polls session-scoped pending handoff cards, using the
existing owner decision endpoint only after explicit Allow once/Deny once. Failed
saves keep the card/error, busy guard prevents repeated clicks, successful-ID
tracking prevents stale polling from resurrecting a decided card. No auto-approval,
new credential/grant or permissions change. No IDE source changed. Existing active
turn tool cards remain separate; this slice handles standalone handoff approvals.

Focused backend17 passed (15 existing aiohttp warnings), UI9 passed, type/theme/
production build/no-mock passed; Vite large-chunk advisory only. Build initially
caught an unused test import; removed before passing final checks. Fixture paused
for backend isolation guard; production processes never paused. UI built only in
external ui-source/dist, never canonical production dist. Current coordinator
approval deliberately left pending for actual browser decision/acceptance.
Beta unknown home history/guard remains intact. Use Alpha or a separate fixture
lane for new explicit requests; no retry or reconciliation invented. Fixture-only
rollout evidence follows; native/pixel acceptance and voice/media limits unchanged.

**Approval fixture rollout:** source `0fb7ab8c`; fixture PID25226 on the same
58310/58305 loopback URLs, canonical workspace package imports preserved. Fixture
alone now serves passing external ui-source/dist. New served index-Vd-L-tPZ.js
SHA256 c515389372634df87660ea2d899377bddcd2d9174ac754fef88ec3d5bbd1535f;
CSS index-BijpUMNE.css unchanged9608489256be019316ad15e41b6797a3cdd0914fe42f3aa2f4700bc02a3b8518.
HTML/all assets match passing build byte-for-byte. Browser proxy GET
/v1/approvals?session_id=agent-native%3Aeveryday returns approval_256248f9a08f,
exact saved task, kindhandoff, statuspending and recovered Alpha session. Foreign
session query returns empty. Existing stored row remains sessionNULL and pending;
read-only recovery proved. No coordinator approval decision sent.

Distinct browser-owned-approval-lane-check completed once through real canonical
owner-react pipeline with BROWSER-FIXTURE-LANE-READY; allowed_tools=[]; no replay.
Both diagnostic unknowns preserved unchanged. Beta home stays reconciliation-
guarded intentionally; rejected unique user submission was not retried or moved.
Use Alpha or separately owned lane for fresh work. Saved approval-before.json,
approval-ui.log/backend.log/build.log, approval-runtime.json and updated manifest
under external browser-acceptance-20261019 evidence folder. Production protected
request/handoff/presentation/GlobalStop hashes and served old index-DkqErgZz.js
unchanged; production processes/native window/drafts untouched. Backend/UI repair
not production deployed. Next: coordinator refresh58310 once, select Alpha, review
existing inline pending handoff and explicitly decide; no repeat Follow up needed.
Actual card visibility/decision/result and motion remain browser acceptance steps,
not inferred from tests or asset hashes. Existing icon/history/primary AX acceptance
stands; pixel/native/voice limits unchanged. No further fixture restart planned.

## Activity/approval production rollout and Safari continuity checkpoint — 2026-10-19

Coordinator's additional Safari58310 observations: reload displayed approved
handoff request + completed correlated result. Fresh Alpha prompt "SLOW-STREAM
isolated browser motion acceptance fresh request." submitted ONCE; Waiting for
progress→incremental Streaming token chunks with Stop. Switched Beta during work,
returned Alpha: completed output retained in the same continuous feed; empty-
composer Send disabled/idle restored. No duplicate submission. This establishes
browser-visible streaming/background continuity/result behavior with the scripted
local model, separate from backend fixtures. No pixel animation/star-color claim
from tiny distorted screenshots; no native12591 acceptance inferred. Existing
icon/history/primary AX evidence stands. Final current inline card decision
acceptance remains a distinct coordinator check; fixture kept running unchanged.

Production preflight: exact existing launch jobs own Gateway21888:33418 and
WebUI19711:8790, canonical cwd and canonical workspace package PYTHONPATH already
configured. No launchd edit, dependency install or security/network/auth change
needed. No active/cancelling/admitted request, running handoff or queued/running
task. Three pending approvals (two background_task, one handoff), no live tool
confirmation waiter. Fresh legitimate menubar12591 lease; Global Stop unchanged.
Saved before/preflight hashes include unknown request1, unknown/pending handoffs,
all pending approvals, presentation/primary, sessions and complete message store.

Deployed passing activity source d2e96265 plus approval source0fb7ab8c (current
committed source). No source edits after focused qualification: summary25 pass,
approval backend17/UI9 pass, type/theme/prod build/no-mock pass. No expensive suite
rerun. Passing fixture UI dist copied into canonical external production dist;
previous build recoverable at ~/.cache/jaeger/ui-rebuild-mainscreen/previous/
activity-approval-1792463586/dist. Reloaded ONLY exact Gateway/WebUI launch jobs.
New Gateway25800 on127.0.0.1:33418 and WebUI25804 on127.0.0.1:8790 healthy in
repeated samples beyond90s; real owner12591 heartbeat age0.81s at stable check.
Sole shell12591 exact agent-primary external bundle0.13.0+3a347be8 retained; no
native input/window reload/relaunch or duplicate launch. Native in-memory page's
new frontend-byte acceptance is unverified; serving new bytes does not establish
that an unreloaded WK page loaded them. Existing window can be shown through its
menu-bar control without relaunching/discarding any draft; not attempted here.

Loaded-contract proof, not GitHEAD/health inference: existing production handoff
approval projection now includes task (before false, after true). Production
WebUI nonexistent-session approval query now correctly returns0 (before3 due to
dropped query). Pending approval count3 unchanged. Current source file SHA256s
for server.py/agent_summary.py/jaeger_sessions.py match committed source and are
recorded with process identities in external runtime.json. Managed jobs already
use canonical package paths; the fixture's earlier stale installed-package issue
was not imported into production. No provider/external-agent turn used to probe.

Production HTML/all served assets match passing candidate byte-for-byte:
index-Vd-L-tPZ.js SHA256 c515389372634df87660ea2d899377bddcd2d9174ac754fef88ec3d5bbd1535f;
index-BijpUMNE.css SHA2569608489256be019316ad15e41b6797a3cdd0914fe42f3aa2f4700bc02a3b8518.
All protected hashes match before/after/stable: unknown request1, unknown/pending
handoffs, all3 pending approvals, presentation/primary, sessions, transcripts,
Global Stop. No unknown replay, approval resolution, real-agent mutation or native
draft interaction. No active work after restart. Fixture PID25226/58310+58305
unchanged/healthy, separate UI dist unchanged, retained for final card acceptance.
External evidence: ~/.cache/jaeger/verification/activity-approval-production-20261019/
(before/preflight/after/stable, contracts-before/after/stable, deployment/runtime,
browser-checkpoint.json). Residual: pixel/native visible acceptance, external peer
acceptance and broader paused voice/media remain unverified/outside this rollout.

Final read-only fixture corroboration after coordinator checkpoint: the exact
coordinator approval_256248f9a08f is now resolved with decisiononce; linked
handoff_de3ba2e52f16 is completed. Metadata retains thread/reply parent
browser-fixture-parent; exactly1 origin handoff_result post in Alpha. Fresh
SLOW-STREAM prompt has exactly1 matching request, completed. These durable facts
corroborate coordinator's reported approved request/result and nonduplicate stream;
no decision or execution call was sent by this production rollout. Saved
browser-approved-result.json/browser-checkpoint.json. This updates earlier pending
checkpoint evidence without inferring pixel/native presentation acceptance.

## Final browser approval acceptance — coordinator confirmed, durable correlation verified

Coordinator refreshed current58310, opened Alpha, and saw Conversation approvals
with exact task "Isolated browser follow-up acceptance: return a short correlated
result." under "Allow handoff to Builder?", Deny once/Allow once. Clicked Allow
once ONCE; card disappeared; Browser Fixture Beta Handoff result · Completed
appeared with CONTRACT-ANSWER and Follow up/Open chat. No resubmission or replay;
browser composer empty. This closes the standalone handoff approval visibility /
explicit decision / result browser acceptance gap for this local fixture.

Read-only durable corroboration, exact same fixture:
- Approval `approval_256248f9a08f`: resolved, decision `once`.
- Handoff `handoff_de3ba2e52f16`; admission request `4e0d7a10-025c-4b62-9802-09615c0f735f`.
- Delegate child run `24d69fc32b6642fe`; canonical child request
  `902bf9b77f73705bc12923e2281e1106`: exactly one receipt, completed.
- Worker session `specialist:native:builder:4e0d7a10-025c-4b62-9802-09615c0f`; result output equals that child receipt.
- Thread and reply parent both `browser-fixture-parent`; origin Alpha
  `agent-native:everyday` has exactly one result message `153`.
- Beta home has exactly one intended mirror message `154`,
  not another execution. Both carry identical handoff/child/origin/thread/reply links.
- Frozen child actor `owner:webui`, read_file-only ceiling, specialist identity and
  original context/history preserved; no model-output verification claim.

Evidence: activity-approval-production-20261019/final-browser-approval-acceptance.json
under ~/.cache/jaeger/verification, linked to the existing production runtime /
asset / protected-state rollout evidence. Current production25800:33418/25804:8790
and fixture25226:58310 checked healthy read-only. No additional rollout, restart,
source change, approval decision or request sent for this recording. Production
activity d2e96265 + approval0fb7ab8c rollout remains complete with earlier sustained
health and hash proof; this is its final browser acceptance addendum. Native12591
window untouched. Pixel motion/star color still unprovable from distorted images;
no pixel/native certification. Voice/media remain paused. No suite rerun needed
for documentation-only acceptance recording.

## Ordinary-bot reference popup correction — 2026-10-19

New user screenshot specifies ordinary menu: Pin/Unpin; Move to new section;
Mark as Unread/verified inverse; separator; Rename Bot; separator; Copy conversation
ID; separator; Hide from sidebar; Delete(red). User explicitly chose recoverable
Delete, preserving conversations. Updated ordinary branch order/groups, original
folder-plus/trash SVG glyphs, red danger styling, narrower194px minimum desktop
menu,14px body type/32px rows and inset separators. Primary branch unchanged.
No More/Profile/History controls appended; those remain in Settings/management.
State-dependent pin/read labels retained, not hardcoded to screenshot state.

Move to new section now uses real GET/POST sections and section_id presentation
PATCH, existing operator schema_meta storage/transactions, bounded validated names
and membership. Delete uses PATCH deleted=true (not DELETE); distinct recoverable
Deleted bots Settings group with Restore. IDs/home sessions/context/history/tools/
roles/background work unchanged. Atomic store rejects deleting current primary,
and selecting a deleted bot as primary until restored. System protection and
existing admin/profile guards retained; no new grants, auth or permissions.
Corrupt presentation/section metadata preserved rather than overwritten. No new
runtime state table, identity authority or legacy frontend. Existing sections
renderer and typed actions reused. Menu actions are capability-gated honestly.

Focused backend19 passed (4 existing aiohttp warnings), UI7 passed; type/theme/
production build/no-mock passed, existing Vite size advisory only. Backend fixtures
prove section durability, reversible delete/restore, same home/context and unchanged
registry definitions, owner scopes/primary/system guards and validation. UI checks
cover ordinary exact labels/groups/red danger contract, primary unchanged, management
and primary-flow interactions. Tests used disposable state; no operator mutation.
Fixture paused for backend isolation guard; production still untouched at this
source checkpoint. Passing UI candidate frozen externally under regular-menu-20261019/dist.
Actual serving/route checks and safe rollout recorded below; no pixel/native claim.

**Ordinary menu rollout BLOCKED at live ownership preflight:** code6ddec235 passing,
not production deployed. Foreground shell12591 no longer exists; no JaegerShell
process found. Existing production Gateway25800 has already exited under lifecycle
policy;33418 unavailable, WebUI25804:8790 still serves the previous build. Lease
still names12591, aged252.85s at sample, Global Stop false. No production stop,
restart, launchd/env change or lease edit performed by this pass. Exact fixture
38566 serves the candidate58310 but authenticated requests fail423 lifecycle owner
disappeared. Attempt to create a new owned test fixture was refused before
admission; no live section/delete mutation acceptance claimed. Other pre-existing
test Gateways97479/97490 left untouched. No old fallback or replacement native
launch used to bypass owner disappearance; no native reload/draft interaction.

External regular-menu-20261019 retains immutable passing dist, backend.log,
fixture-check script and rollout-blocker.json. UI7/build logs under prior external
browser-acceptance-20261019; backend19 passed in disposable fixtures with unchanged
registry/history and protected scopes. Pending next step: once a legitimate
foreground app owner is available, continue already-authorized fixture route
checks and safe production rollout of6ddec235; preserve unknowns/metadata/drafts.
Do not infer source completion or previous successful production rollout means
this new ordinary menu is loaded in a native window. No pixel-match claim.

### Message notification delivery truth — 2026-10-19

Bounded source repair: outgoing handoff markers previously said **Messaged** at admission, including approval waits. `_post_handoff_request` now publishes a delivery receipt only after `append_handoff_post_once` durably writes the recipient home transcript. The existing authenticated handoff execution/admission/approval path is unchanged. Delivery does not mean the recipient completed its work. No new send endpoint, grants, or automatic approval.

Typed live/persisted adapters preserve delivery state. Marker text separates requested, approval-waiting, unconfirmed and confirmed states; historical parts without delivery evidence remain unverified. Same-handoff updates replace the marker and delayed admission cannot overwrite confirmed delivery. Grouping respects delivery state. Two recipients retain inline names/original avatars; three or more render overlapping avatars and **N Bots** with the existing recipient disclosure. No proprietary assets copied. This is source/build evidence, not pixel/native acceptance.

Evidence: `~/.cache/jaeger/verification/message-notification-20261019/`. UI notification-focused3 passed (6 unrelated skipped), avatar/transcript13 passed. Initial wider core run19 passed/2 failed: existing hardcoded-lead and local-unread expectations conflict with prior authoritative primary/unread behavior; retained unchanged outside this scope. Build/type/theme/no-mock pass, existing chunk-size advisory. Backend8 passed (9 existing aiohttp warnings), final log backend-final.log; checks cover actual recipient home write, handoff correlation and no delivery event on persistence failure.

Runtime boundary: read-only preflight still finds no JaegerShell, stale menubar owner12591 and no production33418. No lease manipulation/app launch/service restart/served-build change. Unknown request count1 remains; newest saved message-related request is execution_unknown, not delivery proof, and was NOT retried. Cannot establish that it is Matthew's exact reported send or establish a successful live send while owner/Gateway are absent. Existing popup/native pixel acceptance gap remains. Candidate is external/unserved under the evidence directory ui-source/dist. Next: legitimate foreground ownership, then approved coordinated rollout and fresh owned-fixture send/approval/receipt acceptance; never replay the unknown request.

### Ordinary menu rollout — 2026-10-20

Root cause of missing New section/Delete: production frontend still loaded pre-menu build; WebUI process also lacked sections route, despite current Gateway advertising capabilities. Deployed passing canonical UI3628c8a3 candidate (127 source files matched), ordinary-menu/management/primary scoped7 tests passed. Existing live owner42831 and Gateway42878 retained; no active turns/handoffs at preflight. Restarted only exact WebUI25804→81027 with its original environment/auth/state/bind retained; no launchd edits. GET /v1/sections now succeeds and13 eligible nonprimary bots advertise sections/remove. Protected system bots retain restrictions. Delete remains presentation-only recoverable Deleted bots/Restore, no data removal.

Served index and all entry/preload/style bytes match passing candidate; SHA256 records: ~/.cache/jaeger/verification/menu-rollout-20261020/assets.json. Prior dist retained in previous-dist; old hashed assets remain for open page. Unknown1 and pending/unknown handoffs, presentation and Global Stop hashes unchanged; Gateway200 and legitimate renewing shell heartbeat retained. No real-agent mutations. Existing native page NOT refreshed: draft-safety question pending. Thus served rollout verified, new controls in existing native page/visible popup acceptance still pending. Current screenshot's Move to existing-section submenu not implemented: current action is Move to new section with durable creation/assignment. Pixel match not certified.

### Native screenshot acceptance — 2026-10-20

Operator explicitly confirmed empty composer and authorized refresh. Exact existing canonical app-path CUA binding succeeded (sole shell42831); no relaunch/duplicate/lease change. Cmd-R loaded served current UI. Right-click Builder without opening/changing its chat produced native AX rows: Pin; Move to new section; Mark as Unread; Rename Bot; Copy conversation ID; Hide from sidebar; Delete. Readable native screenshot in this Codex conversation shows folder-plus/trash glyphs, grouping/separators, single-line labels and red Delete. This resolves the previous exact-process/capture blocker for this bounded check; does not retrospectively certify other workflows.

Clicked Move to new section: New Section dialog, Builder moves into it, empty Section name, disabled Create. Cancelled. Clicked Delete: confirmation explicitly retains home chat/history and restoration. Captured screenshot and Cancelled. No agent metadata changes or message submissions. App left open on original Jaeger conversation, composer empty. Remaining visual mismatch proven by screenshot: popup/dialog use light palette against dark application; reference popup is dark. Existing-section Move to submenu also remains unimplemented; supported action is creation/assignment to new section. No full pixel match claim.

### Blueprint coding checkpoint — reactions, background projection and follow-up queue (2026-10-20)

Source only; production/native window untouched. Existing GatewaySessionStore remains owner. Admission/queue promotion/completion now writes actual request/turn identity into transcript metadata; legacy message IDs are never presented as request IDs. Reactions validate target session/request, user versus assistant role and server-owned emoji policy; durable activity_history projection supplies monotonic event watermark and duplicate sets append no second change. UI applies backend acknowledgements only. Ordinary correlated home messages request a read-only snapshot refresh; same-home refresh preserves inline older pages and unresolved turns. Home stream reconnect is still incomplete; no whole background-delivery guarantee.

Inline text follow-up queue uses existing queue_items/admission/execution owner. Device drafts and immutable pending submission IDs survive reload; unknown submits offer same-ID lookup without resend. Version-checked edits reject stale text changes; pause/resume and reorder use existing handlers. Fixed producer returning an older promoted request's receipt/cursor for a newly queued item. Queue item editor text and attachments are not yet durable/supported; no claim otherwise. No execution role/tool/grant/history transfer. Legacy reaction backfill not implemented.

Focused evidence external: ~/.cache/jaeger/verification/blueprint-20261020/queue-final-backend.log: 12 passed, 8 aiohttp warnings; queue-final-ui.log: 30 passed across 5 files; queue-final-build.log: TypeScript/theme/Vite/no-mock pass with existing chunk-size advisory. Additional home stream correlation assertion added and affected UI/build rerun. Comprehensive final pipeline and live browser/native acceptance remain pending after remaining feature implementation. Earlier passing verify checkpoint predates these edits. 316 blueprint cases remain proposed coverage, not executed passes.

Ledger correction: GB026/029/032/039/044/045/046/052/059/065/066/076/078 are PARTIAL with continuing in-repo work, not globally BLOCKED. Each records the exact external operation/access limit separately. Feature-specific storage/authorization reconciliation for other rows remains unfinished; generic entries are not evidence.

### Blueprint coding checkpoint — explicit agent creation recovery (2026-10-20)

New UI creation commands persist operation/name/specialty before sending and use existing control_operations receipts for recovery. Same command/payload returns the original registry identity; changed payload conflicts; an unresolved reservation is not executed again. Explicit new-identity collisions return409 without renaming or changing the existing agent's role/configuration. Existing non-command registration callers retain their contract. No schema migration, parallel registry, new grants or execution-policy change. Existing instances and registry JSON remain authoritative; crash after registry write but before receipt is deliberately unknown and requires reconciliation, not retry.

UI restores pending creation on reload and offers Check saved creation; an acknowledged failed command unlocks editing, while unknown keeps the original saved identity. Existing conversation selection/history is untouched except selecting a confirmed newly created identity. Templates/provenance export and richer specialist configuration remain unfinished coding work, not external blockers.

Evidence: creation-ui-final.log8 passed/3 files; creation-build-final.log type/theme/build/no-mock pass; creation-backend.log2 passed/24 deselected/4 aiohttp warnings. Backend assertions cover exact receipt identity, repeated operation, conflicting payload, existing identity/role preservation and unresolved-command nonexecution. These are source/deterministic checks, not current installed/native acceptance. Production unchanged; comprehensive acceptance remains deferred per coding-first direction. Required pipeline after SSE/queue/creation edits: verify-after-queue-creation.log (record final outcome separately when complete).

Final source-check outcome for e8068095 + 078b2e57: verify-after-queue-creation.log PASS all, after final production-source edits: hygiene9; IDE219; WebUI packaging/routing16; Gateway durability14; tiers6; skills5; IDE wire1; WebUI proxy36. Focused UI30/5 files and creation UI8/3 files are separate overlapping runs, not38 unique scenarios; backend reactions/queue12 plus creation2. Isolated build type/theme/no-mock passed. Existing production Gateway33418 and WebUI8790 returnedHTTP200; original PIDs42831/42878/81027 retained. Current feature builds remain unserved, native window unmodified. No GB-wide or316-case acceptance claim. Original coordinator browser fixture38566 restored after temporarily pausing it for test live-state guards; other owned experimental fixtures remain paused.

### Coding-first continuation — templates and custom specialist configuration

Compatibility before production use: additive registry metadata only (template ID/version, operator_instructions, configuration_revision). No new store or server DB schema; previous code ignores and preserves these fields. Existing sessions/home identities and tool/grant metadata remain unchanged. Registry atomic file replacement is reused; revision checks serialize owner Gateway edits, not a new cross-process transaction service. Rollback retains metadata and local jaeger.ui.specialist-settings.v1.* drafts/pending saves. No production data migration or runtime deployment performed.

Three original permission-neutral text templates feed actual creation. Template IDs/versions validated server-side; template creation cannot inherit tools, endpoints, profiles or credentials. Custom specialist settings edit only specialty/summary/instructions, use expected revision, and enter the actual specialist system prompt. Protected built-in/lead/external definitions remain read-only. Existing caller admin mutation/read boundaries retained, including prefixed caller denial. UI preserves stale drafts and their base revision, pending saves reconcile by GET only; it does not infer its own successful save from changed server revision. Current saved values are separately available for review. No template marketplace/export or tool permission editor implemented yet.

Old baseline-verify-isolated.log remains FAILED (fixture writes under ~/.jaeger); browser-failure.json remains timeout with no passed checks. Later verify-after-queue-creation.log is independently passing. An unnecessary new broad rerun was interrupted on coding-first steering; baseline-rerun-external-fixture.log is INTERRUPTED, not pass. No browser campaign launched. New fixture helper paths use explicit JAEGER_STATE_DIR under ~/.cache/jaeger/fixtures/blueprint-* so future fixture writes do not require weakening the live-state guard. Existing archived/production paths untouched.

### Coding-first checkpoint — registered tools/MCP, diagnostics and message search

Settings→Tools & MCP now projects the canonical already-registered ToolRegistry and loaded MCPRegistry; no discovery/connect/check_fn/tool call. Registered metadata is not a grant/availability proof. MCP owner redacts known loaded transport secrets; raw commands/URLs/env/headers/input defaults/errors omitted. Search/filter/refresh errors retain the previous snapshot. Account enrollment/configuration/consent editing and app-resource staging remain unfinished; no credential or grant changes.

Settings→Diagnostics reads one existing SQLite snapshot: status counts, conversation count and bounded unknown identities. Same-ID checks are read-only, reject foreign receipt identity and never retry. No request text, arguments, credentials or paths are returned. Fingerprint is only server.py bytes captured at module import, explicitly not every loaded backend module/UI. No runtime singleton creation, service start, provider probe or new telemetry service.

Profile and Settings agent management→Search messages now searches only that canonical agent's existing metadata/legacy-specialist-bound conversations. Literal SQLite-lower matching, parameterized query, stable message-ID earlier cursor, bounded snippets/previews with explicit truncation. No parallel index/store, admission/read-marker mutation or session navigator. Search dialog leaves main draft/chat mounted; previous-agent delayed responses cannot cross into the new bot's results. Direct full-message jump/Unicode case folding beyond SQLite lower remain gaps.

Final focused results AFTER production-source edits: coding-features-backend-final.log8 passed/60 deselected/7 aiohttp warnings, guard intact; coding-features-ui-final.log10 passed/7 files; coding-features-build-final.log type/theme/Vite/no-mock PASS with chunk-size advisory. templates-tools-backend.log is FAILED due existing fixture38566's concurrent fixture-task-inspection.json write, despite6 assertions passing; preserved independently. Paused only that verified idle owned fixture for final focused rerun; restore after completion. No broad browser/model/native campaign; existing passing verify-after-queue-creation.log predates this source slice, broad final acceptance remains deferred under coding-first instruction. Old failure logs are not converted to passes. Current source builds unserved; production unchanged.

New unused external-cache fixture52270 was closed gracefully after coding-first steering; no browser tests/requests submitted. Its state retained under ~/.cache/jaeger/fixtures/blueprint-current-20261020-1. Future prepared browser scripts accept the new external fixture root; these harness path changes are syntax-checked only, not browser acceptance. Agent knowledge assignment/context admission, marketplace/export, integration configuration, provider controls and remaining ledger work are not complete or externally blocked merely because missing.


### Coding-first checkpoint — canonical Library binding and pinned agent knowledge

Library owner bug reproduced through real authenticated HTTP, without replacing _library: library-owner-before.log1 failed/503, separate startup fixture missing-config warning also recorded. Switched tools._library from CLI main._pipeline to canonical workspace.get_layout, already bound by both Gateway and CLI. library-owner-after.log3 passed with real create/read/search and exact instance DB path. This fixes a disconnected source owner rather than mocking frontend success.

Custom specialist Knowledge management now saves explicit owned managed document IDs as pinned immutable revision/digest refs in existing registry metadata. Shared configuration revision CAS prevents prompt configuration and knowledge saves from clobbering each other. Protected definitions remain read-only. Unknown saves preserve selection/base/pending and reconcile by GET only. Limits are defined once in contract/knowledge.py and advertised to clients; no new schema/store. Library UTF-8 import decodes strictly within advertised byte cap, preserves prior new draft backup, rejects invalid/binary bytes and loads only an unsent draft until explicit Save. No filesystem root or credential access granted.

Actual execution materializes pinned content via the existing Library owner, marks it reference data, and records metadata-only agent.knowledge context. Known global library-read actors retain existing access; prefixed peers cannot acquire it by naming an agent or sending a message. Missing/archived/inconsistent refs fail before model/tool execution, not silent omission. Live and persisted UI parts show loaded document titles/revisions/digests, without counting context as tool work or appending it to the answer. Context capture is at execution start, NOT initial queued admission. Already-loaded context is not retroactively revoked by later binding changes. Binary/OCR imports, full memory management and external-resource broker remain unfinished.

Fixed response-part producer: complete_request now projects immutable activity_history, not the bounded/pruned SSE events table. Scoped retention test proves early context and tool receipts survive pruning. No unknown request replay. After final backend cap/configuration edits knowledge-contract-final.log5 passed/28 deselected/7 warnings; prior affected knowledge-backend-final.log51 passed/14 warnings includes route/proxy/parts regressions. After last UI receipt/order edits knowledge-ui-last.log20 passed/6 files and knowledge-build-complete.log type/theme/Vite/no-mock PASS with existing chunk-size advisory. Counts overlap and are not added. Scripted model boundary captured actual pinned v1 context after document v2; this is deterministic Gateway execution, not a paid-model/native/browser acceptance claim. Comprehensive campaign deferred; all source builds remain unserved and production unchanged.

Fixture38566 restoration follows final focused checks; other older owned paused fixtures retained. Old failed artifacts and later passing logs remain distinct; final whole-app acceptance and remaining79-group reconciliation still incomplete.


### Coding-first checkpoint — reusable workflows over Library and Task owners

New Workflows settings uses normal name/description/titled-instruction fields, with explicit JSON import/source review. No imported URL fetched, module loaded or step executed during edit/save. Invalid source stays local; new-draft backups recoverable. Existing managed Library documents/versions/archive now classify workflows in existing collections; no new DB schema/store. Original format/limits/classification are defined once in contract/workflows.py. Read/edit/version conflicts/archive/restore use real backend handlers and control receipts. Existing Library default creation payload/id behavior is preserved.

Propose saved workflow run confirms exact saved revision and origin; unsaved edits excluded. Existing TaskOwner creates one unapproved paused proposal with original caller/workspace/model and pinned workflow revision/digest/goal. Current Tasks handles approval/results; no auto-approval, new executor or permission grant. Repeated command ID returns its existing proposal even after definition changes. Archived workflows cannot propose; restore never starts work. Unknown control operations never execute again. Definite Global Stop/auth/validation rejection retains the draft without inventing unknown execution; lost transport remains uncertain. Per-operation client journals retain every ID even when tabs race on a pointer, and settlement clears only its own identity.

Initial workflows-backend.log FAILED2/1 pass at invalid test Config (required model missing), before workflow behavior; retained. Corrected workflows-backend-final.log4 passed/37 deselected/4 warnings covers real authenticated Library/Task owners, version pin/CAS, one paused task/approval after replay, archive/restore, unsupported grant/unknown no effects, external caller denial and proxy. Final shared classification constant regression is workflows-backend-last.log, pending completion here. UI workflows-ui-checkpoint.log7 passed/3 files after last UI journal/form edits; workflows-build-checkpoint.log type/theme/Vite/no-mock PASS with advisory. No comprehensive live/model/browser/native campaign or production changes. Proposal admission is not successful execution; that acceptance remains pending.

GB047/060/072/075 global BLOCKED labels also changed to PARTIAL: actual credential/security, financial, unknown proprietary-admin, signed distribution/install operations are separately restricted; safe local UI/backend portions remain code work. Other generic ledger cells still do not constitute traced coverage. Voice/large avatars remain paused.

Workflow final focused outcome: workflows-backend-last.log4 passed/37 deselected/4 warnings after final backend edits; workflows-ui-checkpoint.log7 passed/3 files after final UI journal/ordinary-form/rejection edits; workflows-build-checkpoint.log PASS type/theme/Vite/no-mock. Original idle fixture38566 restored after checks; no production/native interaction. Broader pipeline and live-model/browser/native acceptance are deferred under coding-first direction, not counted as current source verification.


### Coding-first checkpoint — channel observation and no callback replay

Fixed producer duplicate risk in Discord/Telegram/iMessage bridge callbacks: handler signature is inspected/bound before invocation, modern `(text, session_key=...)` and legacy `(text)` supported; a handler TypeError after an admitted effect propagates once, never retried with a second signature. No changes to allowlists, session trust, slash-command admin gates, credentials or caller authority. Local tests construct bridge objects without SDK initialization, connections or OS Messages access.

Settings→Channels now calls authenticated GET /v1/channels over the proxy. It reports only current Gateway-process bridge/adapter registration and transport thread observations; static catalog maturity is separate. Connection health/delivery remain explicitly not probed/verified. Other processes unobserved, no automatic legacy messaging-daemon fallback. Connect/disconnect/durable bot binding still need a Gateway-native authenticated/correlated ingress and truthful lifecycle acknowledgements; this is missing code, not a global external blocker. No fake controls added.

channels-backend.log8 passed/76 deselected/3 warnings; channels-build.log type/theme/Vite/no-mock PASS with advisory. Tests cover callback effect then TypeError exactly once on all three bridge classes, legacy call shape, unsupported shape never executed, state collection without starts, real authenticated read/prefixed denial and proxy. No external provider/credential/network/app interaction. Source only, current UI unserved, comprehensive acceptance deferred. Original idle fixture38566 restored after focused checks.


### In-flight Tasks proposal durability — compatibility boundary

Client task nonce identity is being separated from native parent-turn/multi-goal dedup. New HTTP submissions use a stable client nonce plus immutable submission fingerprint/original goal in existing Task provenance. Native agent-created multi-goal/key behavior remains unchanged. Existing task IDs/records are never rewritten. Bounded lookup finds legacy/current source=client submissions by originating session/request ID, excludes turn-owned/workflow/schedule records, and refuses ambiguous/conflicting legacy associations rather than admitting another task. No schema migration/index/new store. Older code lacks this new nonce contract: on rollback preserve/read existing Tasks and journals; never replay uncertain POSTs.

Authentication attribution is frozen from the real HTTP caller, not execution-body input. Origin attribution derives from the existing conversation without changing execution owner or role. Per-command device proposal journals/drafts and per-task edit drafts preserve unknown outcomes and exact proposal versions; no automatic create retry on navigation/reload/check. This section is in flight until final focused checks; not a completion claim.

### Tasks / Skills / conversation files source checkpoint — 2026-10-20

- Tasks: immutable client nonce fingerprints, bounded read-only original-submission lookup, authenticated actor frozen by HTTP owner; proposal and edit drafts survive board close/reload. Unknown POST never replayed; newer device drafts preserved. Original command remains identifiable after saved proposal edits; ambiguous legacy matches/conflicting bodies409. Native intentional multi-goal admission and existing approval scopes preserved. Unsaved task edits disable that task's approval; identity-mismatched edit ACK retains draft.
- Skills: exact name/category registry metadata inspection, declared origin/lifecycle/class/platform/tool/toolset/plugin requirements; explicitly unverified origin and unprobed availability. No skill body/path access, toolset loading, install/publish/grant implied.
- Chat Files: existing attachments only, sanitized metadata; registered/staged files explicitly distinguished in copy. Reads confined to original session's staged root/current workspace, regular-file/size/SHA256 checks with descriptor-relative no-symlink traversal. Foreign IDs404; changed/missing/unconfined409. Shared UI verifies identity/size/hash, literal UTF8 text up to1MB and safe raster blob preview, verified byte download. HTML/SVG never executed. Legacy no-hash/no-workspace access explicitly unavailable. PDF/spreadsheet viewers, generated-artifact integration and native download completion remain unfinished/unqualified.
- Final affected checks: `tasks-skills-files-backend-final.log` **62 passed,5 warnings** (real local HTTP/auth/storage plus owner/proxy regressions); `tasks-skills-files-ui-final.log` **11 passed,4 files**; `tasks-skills-files-build-final.log` theme/type/Vite/no-mock PASS (existing chunk-size advisory). Earlier `tasks-skills-files-build.log` FAILED React ref typing; corrected and final rerun passes. Counts overlap earlier focused logs; do not sum. Existing old failed browser/isolation artifacts remain separately failed. No comprehensive pipeline/browser/live campaign rerun under coding-first direction.
- Ledger extended in place with implementation_state/code_remaining/restricted_activation_or_test; existing open-gap text retained, no PARTIAL/UNTESTED promoted to done. These groups still have code_remaining; bounded implemented portions await later acceptance separately.
- Production/native/data/unknown request untouched. Builds external and unserved. Owned idle browser fixture38566 briefly paused only during guard-protected tests, restored running; no fixture requests sent. No migration beyond additive Tasks provenance; old code lacks nonce recovery semantics, so rollback must never replay unknown submissions. Existing popup/native visual gap remains.

### MCP lifecycle / private in-app notifications source checkpoint — 2026-10-20

- MCP: existing loaded registry now supports guarded disconnect and reconnect of its unchanged retained configuration. Active calls reject lifecycle changes. Strict SDK close must succeed before unregistering tools; uncertain close/connect/call blocks further calls/actions in current registry. No claim that disconnect cancels remote effects. Hashed control ID avoids publishing command/URL/env/header/config. No external connection was touched.
- Durable lifecycle uncertainty: existing control_operations plus additive schema_meta resource-command pointer prevent using a fresh operation ID to bypass unknown lifecycle after process/client restart. Per-resource device journal only checks original receipt; never retries. Reconnect requires explicit UI confirmation and can contact an existing configured server only when eventually activated; credentials/permissions are not accepted by these routes. Disconnected intent itself is currently process-local, not a startup policy.
- Notifications: actual event producers now mapped: `agent.handoff.finished` payload.handoff, `turn.failed`/`turn.unknown` from complete_request, approval.request/task.updated/proactive. Initial nonexistent handoff.updated/turn.error mapping was corrected, not accepted as wiring. `mcp.changed`/`notifications.changed` registered in EVENT_TYPES. Tests invoke actual `_publish_handoff` and complete_request producers, retaining fixture unknown without execution/retry.
- In-app center provides metadata-only titles/status, no message/tool/error previews, monotonic read watermark and shared operator enable/mute preferences with CAS and preserved device draft. Muting never changes chat unread, approvals, work or identity. Existing schema_meta additive notifications key; no new store/schema or OS authorization request. Rollback retains the key/journals; older source ignores settings. Native banners/dock/quiet hours/pagination/global-only no-origin handoffs remain code work.
- Final affected checks: `mcp-notifications-backend.log` **51 passed,5 warnings**; `mcp-notifications-ui-final.log` **8 passed,4 files**; `mcp-notifications-build-final.log` theme/type/Vite/no-mock PASS, existing chunk advisory. Local SDK stand-ins qualify guards/owner wiring, not actual external transport lifetime. No broad acceptance campaign, production changes or paid model work. Fixture38566 restored running after checks.
- Ledger in place: explicit code_remaining and implemented_slices_awaiting_acceptance; paused EXCLUDED rows now implementation_state=excluded. No PARTIAL group promoted to done. Channel controls/bindings, memory/resources and remaining package code continue; no global blocker invented from absent UI.

### Channel inbox / configured controls source checkpoint — 2026-10-20

- Existing owner: per-channel binding in existing Gateway schema_meta; canonical existing bot ID+revision CAS, no role/tool/history changes. Connection is a separate confirmed operation using existing instance credentials and parsed nonempty allowlist, not a credential/config editor. Existing bridge/adapter cannot be silently replaced. Existing scoped control receipt pointer prevents unresolved-lifecycle nonce bypass; device draft/command journals retained.
- Ingress: SDK message IDs reach new callback shape without retrying legacy callbacks or effectful TypeErrors. Mandatory channel conversation/provider-message ID deduplicates into existing background_deliveries; same body/target returns original receipt, changed identity payload conflicts. Appends incoming_data_only channel_message into same home feed; creates **zero** model requests/approvals/tool work. Global Stop/live lease still blocks new admission. This is a working data inbox source path, **not** automatic bot reply execution or external delivery proof.
- Producer repairs: Telegram parked event is signaled and polling/application shut down on original bootstrap loop, stopped handle retained on failed exit; iMessage clears stop flag on restart and verifies exit; Discord binds actual loop on ready and handles pending-stop. Matching bridge/adapter only removed after exit, bus callback unsubscribed. Active handler gate blocks stop/new admission races. External/provider cursor catch-up, approval-bound automatic replies and durable outbound receipt correlation remain implementation work.
- Compatibility before activation: additive binding/resource metadata and delivery receipts, no schema/new store. channel_message is additive typed transcript kind with whitelisted attribution. Older shared UI may mislabel it; do not activate new channels with old UI. Rollback retains transcripts/bindings/command journals; never replay unknown operations. No migration, external network/SDK/OS Messages DB or production service change performed.
- Checks: `channel-controls-backend-complete.log` **66 passed,3 warnings**; `channel-controls-ui-complete.log` **17 passed,2 files**; `channel-controls-build-complete.log` theme/type/Vite/no-mock PASS. Local actual bridge threads exit/restart using local SDK stand-ins; not actual provider qualification. Previous backend logs FAILED missing kind then incorrect attribution contract expectation; repaired typed producer/consumer and retained both failures. Initial build FAILED type narrowing; final passing build separate. No broad/live/browser/native campaign. Owned fixture38566 running again; real unknown request untouched.

### Specialist notes / memory source checkpoint — 2026-10-20

- Existing `jaeger_agent.tools.agent_notes` is now the **same writer** used by operator API/editor: cooperating model-tool/API mutations share flock, content SHA256 CAS, atomic replacement, private recoverable prior-content versions and existing file-mode preservation. Read-only note mode refuses mutation. Empty destructive clears unavailable. Generic/manual filesystem writes do not participate in this protocol; no universal filesystem-writer guarantee claimed.
- Scope producer repaired: new note directories derive immutable agent IDs. Uniquely owned existing legacy directory remains authoritative in place; colliding legacy names, reserved namespace or old+new notes both present fail visibly rather than share/overwrite. No operator data was inspected/moved/migrated. Runtime must retain current source for new ID paths; rollback to name-only source needs explicit mapping before activation, preserving every file/version.
- GET/POST canonical agent memory routes use existing read/admin and protected-agent rules; no outside caller/global memory access added. Exposed specialist note text only, no execution definition/role/tool/credential/session changes. Tool prompt still loads only4,000 chars while owner stores at most16,000 chars for new writes; budgets come from same owner. Unknown operation reads receipt only, never replays. Existing notes/history remain distinct from Library reference bindings and entity memory.
- Settings→Agents→Memory shows actual saved text/budget/revision, persistent draft/base, separate per-operation immutable journals, read-current review and in-app confirmed version restore. Restore keeps an independently unsaved draft; later agent changes do not fabricate failed saves or discard drafts. Unicode character count follows backend code points, no silent text truncation.
- Checks: `agent-memory-backend-final.log` **55 passed,3 warnings**; `agent-memory-ui-complete.log` **2 passed**; `agent-memory-build-last.log` type/theme/Vite/no-mock PASS. Local HTTP/store/prompt/history/role invariants, actual concurrent append serialization, stale rejection, restore/versions, readonly mode and legacy collisions covered. Initial backend log FAILED old name-path assertion; updated to immutable-ID contract, not weakened tool/permission checks. No paid model/native/browser campaign or production change; fixture38566 restored running. Broader entity memory/resource/search/provenance workflows remain code_remaining in ledger.

### MCP resource inspection / reviewed import — source only, 2026-10-20
- Existing MCP registry now exposes explicit opaque catalog handles, bounded volatile redacted text snapshots and reviewed import into the existing managed Library owner with original-source digest provenance. No arbitrary URI, automatic provider fetch, automatic knowledge pin, grants or new connection initialization. Shared Tools dialog uses typed proxy routes, immutable operation journals and original receipt inspection.
- Catalog name, description AND MIME use the same loaded-secret/safe-text redaction before UI or receipt projection. Local fixture echoes a dummy transport secret in each field, raw URI and cursor; tests check returned catalog, preview, saved receipts and imported metadata. Raw cursor/URI stay private.
- Focused backend `mcp-resources-backend.log`:52 passed,1 warning; UI `mcp-resources-ui.log`:1 passed; `mcp-resources-build.log`:type/theme/Vite/no-mock PASS, existing chunk-size advisory. Additional receipt assertions: `mcp-resources-redaction-final.log` assertions2 passed but overall FAILED isolation because the existing browser fixture updated its inspection JSON concurrently; retained as failure. Isolated rerun recorded separately, guard unchanged.
- Compatibility: optional managed-document provenance added to existing creation payload; no new database/schema/store/service. Resource previews/page handles are volatile and intentionally expire on restart/disconnect; expired receipts never trigger automatic reads. Existing document edits retain original import provenance, not a claim about current edited content or publisher trust. No production migration/activation performed; unsent drafts/history/unknown requests untouched. Live SDK/provider/native acceptance remains pending; MCP setup/permissions and broader ledger scope remain code_remaining.
- Final receipt/redaction rerun `mcp-resources-redaction-isolated.log`: **2 passed**, exit0; idle browser fixture resumed. No live-state guard bypass.

### Memory context / recoverable forget and resource-dialog regressions — source only
- Settings→Agents→Memory now searches current saved notes through the same authenticated read route, shows observed notes-context prefix and content SHA, explicitly records author attribution as unavailable. Correction uses existing revisioned replace. Confirmed recoverable forget removes only future saved-note prompt contribution, archives prior bytes through the same locked owner and supports existing restore. Model notes tool cannot call operator forget/restore. Already admitted context/history/identity/roles/tools/permissions unchanged; separate unsent correction draft preserved.
- Compatibility: no schema change or new store; empty NOTES.md after explicit forget is intentional and earlier nonempty revision remains recoverable. Rollback reads empty notes normally; preserve .versions and device operation journals. Generic filesystem writers remain outside the cooperative lock. Search is current saved lines only, not entity memory or prior versions; context is an observation, not proof of exact context in a running/next turn.
- Resource dialog now has targeted local component journeys for explicit catalog→read→literal preview→confirmed Library import and unknown receipt→expired local cache without provider replay. These complement backend tests; not browser/native acceptance.
- Checks after edits: memory-context-backend.log **50 passed** (notes owner/API/proxy); memory-resource-ui-final.log **5 passed** (3 memory,2 resource); memory-resource-build-final.log type/theme/Vite/no-mock PASS. Earlier test-descriptor TS build failure retained separately, corrected descriptor contract. No production/external activation or real user metadata edits.

### Installed plugin catalog / managed hooks; native notification truth — source only
- Settings→Tools & MCP now shows installed extension entry-point distribution metadata without loading code, plus registry-observed load/hook counts. Discovery is staged/idempotent; failed registration discards staged context and remains outcome_unknown without retry. Changed distributions cannot overlay loaded code in-process. Confirmed hook pause/resume uses active-handler protection, existing authenticated owner control receipts and original-operation recovery. No install/update/unload, tool retirement, transport stop or durable disabled-startup policy is claimed.
- Existing native notify producer no longer reports queued before macOS decides. notifications.status reads authorization without requesting it; notify submits only under existing authorized/provisional status, returns actual OS acceptance/error, explicitly not proof of banner display. Settings reads status and permits an explicit fixed-content local check only when authorized. No automatic native delivery, permission request or actual OS notification performed. Existing native visual popup gap remains untouched.
- Compatibility: plugin controls only current-process managed hook dispatch, restart retains discovery default. Operation receipts remain in existing Gateway store. Native notify result changes queued→accepted with notification_id/delivery_proven:false; old callers must not infer visible delivery. No schema migration or production activation.
- Focused checks: plugin-catalog-backend.log **53 passed**; plugin-catalog-ui.log **2 passed**; plugin-catalog-build.log PASS; plugin-native-ui.log **4 passed**; plugin-native-build.log PASS; native-notification-contract-final.log **11 BridgeTests passed**, shell executable compiled into external scratch. Initial native compile FAILED unavailable macOS ephemeral authorization case; removed unsupported case and reran successfully. Existing Swift sendability warnings retained. No installed/native-window acceptance.

### Correlated external-channel replies / durable effect truth / opt-in native consumer — source checkpoint
- Ordinary owner path: actual saved channel DTO→typed turn→Prepare bot reply fills only an empty recovered composer and never submits. Existing user Send/admission/model/tool path remains responsible for execution. Same send_message tool now accepts reply_to_message_id; Gateway binds resolver in normal _execute_turn, rechecks actual saved row/session/destination, active request, current inbox binding/allowlist and Stop/lease before transport call. No new tool, permission grant or incoming-data auto-run.
- Discord author and destination are separate: actual on_message uid passes through _safe_handle→call_handler_once→inbox→message metadata as ingress_author_id; provider_conversation_id remains discord:<channel>. Reply validates saved AUTHOR against allowed_users and exact requested destination against saved CHANNEL. Telegram still validates chat ID; iMessage handle. Missing-author legacy Discord is refused, never inferred from channel ID. External-effect approval target now includes channel, recipient and saved parent ID. Author metadata conveys provenance, not execution authority.
- Model context is wired at producers: contract/channel_messages.reply_reference feeds owner ContextCompiler JSON and direct model role/content projection. Both retain authoritative numeric saved parent ID, channel, destination, optional author, incoming_data_only and existing-policy requirement. JSON escaping/budgeting preserved. Normal Gateway admission→actual prepare_turn/projector→local model-boundary fixture validates context and automatically bound resolver, not a manually installed scope. Model and memory I/O collaborators in that fixture are isolated; not live-model proof.
- Submission truth: Telegram/Discord/iMessage exceptions/partial sends remain unknown; adapter no longer converts a nonreceipt into success. Existing SQLite effect ledger retains accepted results, or partial known part IDs on an unsettled claim. Model loop marks this nonretryable/effect_indeterminate; public tool outcome unknown. Channels reads only loaded entity send_message effect metadata with pagination; no body leakage/new store, retry/resolve control or proof of recipient delivery. Local permission denial prevented an actual fixture file effect; approval produced one effect, reopened receipt prevented duplicate; partial fixture remained pending across reopen and never resent.
- Native metadata delivery source: default-off per-device opt-in, existing OS permission only, quiet hours/local time, cross-tab Web Lock, observed-history baseline and cursor claim before native IPC. Lost acknowledgment never replays on reload; absent coordination/history rollback fails closed. In-app mutes/read/off/quiet activity is not queued. Only metadata summary is submitted, never chat/tool text. No OS permission request, real notification or native/window interaction performed. Native click navigation/badges and broader notification controls remain incomplete.
- Compatibility/rollback: additive channel author metadata/fingerprint only when author known; old duplicate lacking author cannot be silently upgraded. No database schema/new store/service. Existing effects.result_json may hold partial receipt while status remains pending; old code must preserve pending claims, not replay them. Unsettled calls with the new optional tool argument require current compatible source; never strip argument/replay. New device preferences/cursor default off; preserve on rollback. No production data/migration/activation performed.
- Final focused evidence: channel-notification-scoped-final.log **43 passed,11 warnings**; channel-composer-native-final.log **24 passed**; channel-composer-native-build-final.log type/theme/Vite/no-mock PASS (existing chunk advisory). Native shell source unchanged since prior passing compile/11 BridgeTests. Earlier channel logs FAILED fixture seeding across runtime attachment/restart and wrong noncanonical fixture home; logs retained, fixed fixture ownership and disk readback. No broad acceptance campaign, provider connection, external message, production change or unknown-request replay. The original native popup/pixel acceptance gap remains.

### Notification retained-history paging / categories — source continuation
- Existing activity_history owner now advertises category IDs and accepts validated category/before filters,50 emitted/500 scanned rows per page, observed cursor and bounded older-page cursor. Typed Gateway/proxy/shared UI carry both query parameters. No new store, writes, external connection or notification permission needed for reads.
- Notifications UI appends/deduplicates older entries, preserves those pages during polling, rejects late responses after category changes, and applies current mute/read preferences to retained rows. The existing global read-watermark policy is now disclosed as displayed-and-earlier across categories/mutes; no claim that marking one page affects only those visible entries.
- No persisted migration: existing preference CAS/read watermark unchanged; device opt-in/quiet preferences remain independent. Compatibility is additive GET fields/options. Native consumer remains default off and requires both current permission and exclusive coordination; unsupported host/old Gateway fails closed.
- Checks after UI edits: notification-paging-ui-final.log **6 passed**; notification-paging-build-final.log type/theme/Vite/no-mock PASS. Final backend API/proxy log follows after last validation assertions. Browser/native/full live-model acceptance remains deferred; no production changes.
- Final notification-paging-backend-final.log **49 passed,5 warnings**, including last API validation and exact proxy query preservation; owned idle browser fixture resumed. Source diff whitespace check PASS. A read-only disk scan found two pre-existing ignored bytecode files (jaeger_ai/__pycache__/__init__.cpython-312.pyc, modified2026-10-18; dev/__pycache__/bytecode_guard.cpython-312-pytest-9.1.1.pyc, modified2026-10-17). Current runners use -B/PYTHONDONTWRITEBYTECODE/external prefix; no new bytecode asserted. Old artifacts left untouched under no unrelated cleanup scope; no disk-pristine or full verify-pipeline claim for this checkpoint.

### Entity semantic-memory inspection — source continuation
- Settings→Memory now uses the resident entity's existing semantic/world owner for literal subject/predicate/value search, cursor paging, current versus expired history, recorded source/provenance/confidence, full saved-content revision and observed recent12 context-candidate flags. Not an admitted prompt snapshot or independent fact/publisher verification. Views remain literal/escaped, bounded previews and retain prior results on failure.
- GET /v1/runtime/memory/claims uses the loaded EntityRuntime instance only; absent owner is explicit, never initialized by the read. Existing authenticated read; prefixed peers denied. No database/schema/index/store/service added. Underlying query_claims now excludes expired claims by default, consistent with list_recent_claims; include_inactive=True preserves explicit history access. No old claim is deleted or rewritten. No real user memory was read or changed in these checks.
- Compatibility: additive read route/fields; explicit historical query option. Correction/recoverable-forget mutations for structured claims remain code_remaining, distinct from implemented specialist-note correction/forget. Older source ignores new read view; original claims remain intact. Context may change before admission; candidate tag is only observation.
- Checks: entity-memory-backend.log **55 passed** (world owner expiry/search/page/bounds, real HTTP read-only/no-runtime-init/peer scope and proxy regressions); entity-memory-ui-final.log **1 passed**; entity-memory-build-final.log type/theme/Vite/no-mock PASS. External build remains unserved; no runtime/production/OS action or broad acceptance campaign. Owned idle fixture resumed; existing unknown execution never replayed.

### Structured semantic claim management — source checkpoint, 2026-10-20

Existing resident entity `SemanticMemory.world_store` now owns revision-checked correction, recoverable forget and restore. Settings→Memory→Inspect claim exposes recorded source/provenance, recent management history and correction lineage; independently saved correction drafts survive rejected/uncertain changes. No specialist role/tool/permission/history changes. This is source/fixture evidence, not production/native acceptance.

Compatibility/recovery before activation: no new database or table. Existing `knowledge.sqlite3` claims/evidence retain originals; one additive evidence target/source index. Corrections expire the original and create a new **told** claim attributed to the authenticated actor, never inheriting verified status. Forget expires future semantic retrieval only; it does not erase transcripts, old evidence or already admitted context. Restore reverses only the latest operator forget and never extends its original expiry. SYSTEM-derived claims remain protected. Management IDs participate in revision hashes, preventing stale writes after forget/restore. A transaction commits mutation, audit and domain receipt together; that receipt recovers a crash before Gateway acknowledgment without command replay. Existing Gateway control-operation fingerprints reject command identity reuse. Keep evidence and device draft/journal keys during rollback; older readers still respect claim validity. No production migration or real memory mutation performed.

Focused evidence: `~/.cache/jaeger/verification/blueprint-20261020/claim-management-backend-final.log`:60 passed/1 existing aiohttp warning; `claim-management-ui-wire-final.log`:4 passed; `claim-management-build-wire-final.log`:type/theme/Vite/no-mock pass (existing chunk advisory). Initial build failure from incomplete test fixture/UUID types preserved in `claim-management-build.log`; repaired without weakening assertions. Wire review also corrected a RequestInit-vs-body adapter mistake before final wire check. Final receipt-read defensive edit rerun `claim-management-backend-receipts-final.log`:60 passed/1 existing aiohttp warning. Owned idle fixture38566 paused only during guard-protected pytest and resumed; production unchanged. Unknown real request untouched.

Remaining GB-062 code: actual admitted-context snapshots, episodic/procedural/reflective owner controls and semantic/vector search. Recorded context candidates are explicitly not proof of prompt admission. Full browser/native/live-model acceptance deferred by coding-first direction. Popup/native visual gap and paused voice/large-avatar exclusions remain.

### Provider configuration, package revision drift and context provenance — continuing source work

Provider inventory no longer hardcodes every cloud provider as unconfigured. It uses the execution credential resolver and saved `external_model` credential/env selectors, returning configuration presence only (`not_probed`, `not_configured`, or inspection `unknown`). No provider contact, health success or cloud model entitlement inferred. Inventory work moves off the async request loop. Settings retains the saved unavailable model on refresh; no fallback or credential mutation. Review reproduced `Path.root` resolving to filesystem `/`; the shared resolver now normalizes Path/string inputs through a pure `InstanceLayout`, without initialization/migration. It also no longer rereads a protected credential via an unchecked raw-file fallback. Dummy file/env fixtures mask ambient credential fallbacks, use the real resolver, assert exact custom selectors, unchanged content/modes and rejection of an over-permissive fixture file.

Plugin owner catalog now distinguishes current distribution from removed/replaced files and a newer installed revision blocked by retained code. Hook resume refuses removed/replaced identity; pause stays available where supported. UI explicitly says tools/commands/background activity remain retained. No package activation, environment installation, unload, transport stop or startup policy change. Package install/update/restore/uninstall and durable startup policy still require implementation; this is a prerequisite, not lifecycle completion.

Context producer repair: `SemanticMemory.list_recent` retains immutable claim ID/source; `ContextCompiler.select` preserves epistemic provenance and zero confidence instead of calling all claims Fact or converting0→0.9. This is compiler projection evidence, not a persisted actual model-boundary prompt inspection feature. No added data store or historical rewrite.

Compatibility: provider/config changes are read-only, no schema migration; existing session choices and protected credential files unchanged. Plugin additions are process catalog fields/guards only. Context dict metadata is additive; legacy claims without IDs/provenance remain explicitly unknown. Production/drafts/user memory/unknown executions untouched. Full live-model/browser/native acceptance remains deferred. Original popup/native acceptance gap and voice/large-avatar exclusions preserved.

Final focused evidence: `provider-plugin-memory-passing-final.log`:60 passed/3 deliberately deselected ambient/runtime catalog probe cases/2 existing aiohttp warnings; UI `plugin-provider-claim-ui-final.log`:8 passed; `plugin-provider-claim-build-final.log`:type/theme/Vite/no-mock passed (existing chunk advisory). Earlier `plugin-provider-resolver-final.log`:1 failed/38 passed/3 deselected, caused by incomplete owned Config fixture, preserved as FAILED; fixture repaired with required instance/model fields. Earlier mocked-resolver checks are supplemental and superseded for Path/selector proof by the real dummy-file fixture. No comprehensive suite, paid model or real provider acceptance claimed.

Final producer-regression run uses the real owned credential file/config/env fixture and existing execution resolver; the earlier mocked forwarding test was replaced. `provider-plugin-memory-final.log` remains FAILED (1 failed/59 passed/3 deselected): its old human-format assertion was updated to assert the full structured claim JSON, unknown provenance and absence of a Fact prefix. No assertion was dropped; final run above passes. Focused command: `python -B -m pytest dev/tests/jaeger_ai/test_plugins.py dev/tests/jaeger_ai/core/test_external_model.py dev/tests/jaeger_ai/core/test_context_compiler.py dev/tests/jaeger_ai/core/test_world_state.py dev/tests/jaeger_ai/core/test_runtime_truth.py -k 'not capability_snapshot and not prompt_block and not webui_catalog_shape and not product_default_runtime_prompt' -q`, with external bytecode/cache paths and owned idle fixture38566 paused/resumed. The three ambient-probe cases were intentionally outside this isolated coding checkpoint, not counted as passes. No broad acceptance or new runtime rollout performed.

### GB-042 — offline package lifecycle and durable startup policy (source, 2026-10-20)

Tools→Installed extensions now wires durable disable/exact-revision approval and a real local-wheel review/install/update/recoverable removal/restore flow. Existing conversation attachment staging is reused; selecting/reviewing a file submits no chat/model request. Digest, installed-file fingerprint, startup revision and immutable operation ID bind each confirmation. A lost upload acknowledgment resolves its original staged row; a lost package acknowledgment reads the existing receipt/progress instead of rerunning pip. Old backups remain reachable through paged receipt history. Separate explicitly reviewed compensation preserves the original unknown journal/outcome.

Owners/boundaries: `plugins/registry.py` retains loaded identities/hooks; `plugins/packages.py` uses pip in the server-fixed external Python environment. Existing Gateway `control_operations`/`schema_meta` own startup policy, progress and resource admission; no new DB, service or parallel runtime. Discovery reads existing policy read-only without initializing a database/runtime. Approval binds to actual file hashes/RECORD, not name/version alone; same-version tampering cannot inherit approval. Public catalog IDs remain stable. Policy is scoped to resolved environment prefix (stable across Python upgrades at that prefix). Legacy discovery default remains until explicitly changed; relocation to a different environment is not a policy migration. Startup changes grant no new tool access, load no code and start no connection; in-process extension code is not sandboxed. Existing read/admin/prefixed-caller/Stop/live-owner rules retained.

Before any environment change, exact original package files/provenance/modes and a valid recovery wheel are retained under `<operator state>/artifacts/plugin-packages/<environment>/<hashed operation>/`. Selected wheels keep their canonical basename under `selected/` (the reviewed `selected-...whl` defect is fixed). Wheel hashes/RECORD, namespace/entry-point shape, current installed bytes and existing local dependencies are checked. Installer uses isolated/no-site/no-bytecode Python and offline pip; no index, build, dependency change, .pth hook or plugin import. Core/shared/mixed-script/in-use packages are protected. A guarded owned installer is stopped on Stop/timeout; unknown/partial outcomes are retained. Success proves observed installed file state, not historical installer delivery or plugin functionality. New/updated/restored packages remain startup-disabled. Loaded/currently used code must retire through a separately coordinated restart before its files change; no hot unload or silent background-work termination.

Compatibility/recovery before activation: existing Gateway schema/tables only, new namespaced metadata keys. Original package archives and browser journals must be retained on rollback. Selected/recovery wheel artifacts are private state files, not a substitute store. Restoring verified original code/provenance/modes is a new admitted operation, never a replay of the unknown install. Missing installer identity or missing/unprovable RECORD ownership fails closed for explicit inspection; it is not settled as a failure or erased. Native/platform wheels, source builds, general plugin-thread teardown and remote trusted publisher/catalog acquisition are unsupported source gaps in the same ledger, not hidden fallbacks or blanket external blockers.

Evidence root remains `~/.cache/jaeger/verification/blueprint-20261020/`:
- `plugin-packages-paged-final.log`:66 passed,2 existing aiohttp warnings. Disposable venv actual offline pip install→update→exact restore→remove→undo removal; restrictive fixture file mode preserved; activation sentinel absent. Real authenticated Gateway upload→review→pip→receipt/readback; duplicate/conflicting nonce, denied callers and Stop guard. Interrupted actual pip update with partial fixture content→new backup compensation; original unknown remains unknown. Durable startup/reload/tamper/corrupt-policy/no-init checks; paging and proxy checks.
- `plugin-packages-paged-ui-final.log`:9 passed. Explicit confirmation, exact upload/digest body, pending receipt remount, no replay/reupload, original unknown journal preserved for new compensating command, startup and typed HTTP checks. These are UI fixtures, not visible browser/native acceptance.
- `plugin-packages-paged-build-final.log`:theme/type/Vite/no-mock pass; existing chunk-size advisory. External unserved build only. `plugin-packages-lint-final.log`:focused F/E9 pass.
- Earlier `plugin-packages-ui.log` remains FAILED (1 failed/7 passed): asynchronous FileReader wait repaired. `plugin-packages-recovery-backend.log` remains FAILED (1 failed/62 passed): fixture compared the message-page envelope to a list; corrected to assert the real `messages` collection is empty. No assertion weakened or failure counted as a pass.

Owned idle fixture38566 was paused only during guard-protected pytest and resumed. No user-runtime package install, production/service change, real user memory/metadata/draft mutation, external connection, credential/grant/security change, unknown real-request replay or publication. Voice/large-avatar exclusions and existing popup/native visual acceptance gap remain. Comprehensive model/browser/native acceptance remains deferred under coding-first priority; other ledger work continues.

Additional owned-process evidence: `plugin-package-owned-process-checks.log`:2 passed/5 deselected. Stop and failure to persist installer identity each terminate and reap only the owned installer process group; installed-version path traversal is rejected before recovery artifact creation. No production Stop or user process changed.

### GB-062 — content-free actual model dispatch visibility (source, 2026-10-20)

Normal Gateway preparation is not the older ContextCompiler event path: candidate semantic claims previously shown in Settings do not prove actual model admission. Added an optional dependency-inverted model-input observer to the existing agent loop immediately after adapter formatting and before each call, including retry/fallback attempts. Gateway direct text/image HTTP dispatch also records its actual payload shape. This observes dispatch intent, not server acceptance/consumption. Raw prompts, history text, schemas/names, attachments, thinking, headers, credentials and content hashes are never persisted. Fixed roles, character counts, separate system length, schema count, omitted block count and unsupported/truncated indicators only.

Existing session-scoped `turn.context` events and activity_history→assistant response parts own persistence. SharedUI live/restored expandable Model dispatch context shows each observation separately in the same continuous feed. No session list, store/schema migration, grant change or execution control added. Existing owner/history authorization applies. Callback failure cannot affect a turn. Rollback preserves additive events/parts and safely ignores unknown receipt kinds; no conversation or unknown-request replay.

Focused evidence under the same external root: `model-context-ui-final.log`:3 passed; `model-context-build-final.log`:theme/type/Vite/no-mock pass, existing chunk advisory, unserved external build. Initial isolated backend run `model-context-focused.log`:12 passed; expanded pre-final-ID run `model-context-backend-final.log`:20 passed. Final ID correlation and persisted response check recorded below when complete. `model-context-syntax-final.log`:F821/E9 pass. Wider F/E9 server lint reports two pre-existing unused imports (DEFAULT_AGENT_MODEL, DelegateExecutionError) already present in4b2cfaa8; not hidden or claimed clean. First UI command used a wrong relative rsync source; its logs are stale-build evidence only, superseded by successful absolute-path copy and the `-final` logs.

Still code work: item-level admitted memory/document/skill provenance through budget/compaction, remaining memory owners/correction/search, unsupported adapter payloads. These outline counts do not certify those features. No real provider, native/browser acceptance or production rollout; paused media and popup/native gap retained. Package source checkpoint4b2cfaa8 is independent and does not imply plugin activation.

Final source check: `model-context-correlated-final.log`:20 passed/13 existing aiohttp warnings after final correlation edits. Real agent loop→formatted fixture adapter→durable Gateway event→completed assistant parts and direct HTTP-boundary fixture both assert exact persisted turn ID; no provider contacted. Owned fixture38566 resumed after pytest; production untouched. Dispatch outlines remain implemented awaiting live acceptance, not full GB062 completion.

### GB-062 — selected owner items through budget/compaction and episodic controls (source, 2026-10-20)

Normal prepare_turn now preserves individual semantic claim, other-conversation event, retrieved document chunk, matched skill and reflection identities through ContextCompiler selection and with_background's actual escaped JSON budget. This replaces flattened normal-path recall text; the existing owner's read paths remain authoritative. Each item receives a fresh private frame reference and complete rendered-fragment comparison after the agent's real ContextGuard and adapter formatting, including retries/continuations. Marker-only/text-only/count matches cannot assert admission. Receipts distinguish budget_dropped, retained_exact, not_retained_exact and unobservable; absence is verbatim absence, not proof of forgetting or provider consumption. Thinking/blob/header fields are excluded. Server-supplied paths/names stay private; opaque owner-record refs and validated canonical claim/event IDs or pinned document ID/revision are public. Existing managed pinned knowledge is framed and observed too, with original caller authorization/revision/digest checks retained.

Settings Memory also wires the loaded entity event-store owner: searchable/paged original episode text, current policy/detail, independent correction draft, reviewed correction note, recoverable exclusion and restore. Existing entity_events holds additive memory.episode.changed events with exact revision CAS, idempotency, actor, source parent and atomic domain receipt; no new store/service. Original events are byte-preserved. Correction is explicit TOLD data beside the original, never verified fact or execution authority. Forget excludes future automatic cross-conversation recall only; own transcript, prior derived memories and admitted work remain. Restore retains correction. Concurrent stale/ABA commands conflict. Existing global owner read/admin, resident OWNER, caller-prefix denial and Stop/live-owner rules apply. Reading creates no runtime. Lost/rejected acknowledgments check both canonical domain and Gateway receipts without replay.

Compatibility before activation: no schema migration; additive event/part fields and private transient PreparedTurn references only. Retain original events, policy records, browser pending journals and correction drafts on rollback. A binary predating recall-policy support would ignore those exclusions: rollback with active exclusions requires keeping the policy-aware reader or coordinated review, never claiming old binaries honor forget. No actual operator memory or production data was changed in this coding pass.

Focused evidence in the existing external blueprint-20261020 root:
- memory-provenance-owner-checks.log:86 passed/6 existing aiohttp warnings; real owner CAS/concurrency/reopen/receipts, auth/residency/Stop/prefixed denial, context compiler, current lane/history and explicit proxy regressions.
- memory-context-dispatch-final.log:11 passed/8 existing aiohttp warnings after pinned-frame integration: real authenticated Gateway admission→actual prepare_turn→local scripted HTTP boundary→persisted response items, real agent compaction retained→not_retained transition, exact pinned revision, item budget/drop and original-history preservation. No provider or external transport contacted.
- Final episode rejection-receipt and UI results recorded below once completed. Broader source counters are not full GB acceptance.
- context-items-first.log remains FAILED (1 failed/21 passed): decoded-envelope confidence assertion repaired, not removed. memory-provenance-owner-build.log remains FAILED: execution_unknown missing from typed ControlResult, corrected to reflect the existing response flag; later final builds supersede it.

Ledger reconciled in place: GB010 no longer claims component-local-only drafts; known reliability/document/reaction/channel/resource/package slices reflect current source and prior evidence. GB042 is bounded to supported registry pending/installed/error/update/removed/restore, not arbitrary wheel/ecosystem parity. GB062 is bounded to Jaeger owner provenance/controls, not proprietary internals or forced mutation APIs for every category. Untested source packages whose exact missing code is not yet established are explicitly unreconciled rather than falsely missing, blocked or complete. All79 original IDs and proposed acceptance criteria retained; no316-scenario pass claim. Voice/recording exclusions and large-avatar pause retained.

Final affected edits: episode-rejected-receipt-final.log3 passed/3 existing aiohttp warnings; memory-context-ui-last.log7 passed; memory-context-build-last.log theme/type/Vite/no-mock pass, external unserved; memory-context-lint-last.log F821/E9 pass. The earlier86 regression checks and11 dispatch/knowledge checks remain separate evidence, not summed into scenario coverage. No full verify/browser/native/model campaign under the current explicit coding-first instruction. Idle owned fixture38566 resumed; production untouched.

### GB-001 — Unicode search and complete saved-result access (source, 2026-10-20)

Existing agent-bound SQLite search now uses Python Unicode casefold through a per-read SQLite UDF. No new search index/store. Literal percent/SQL text remains literal. Folded-offset→original-codepoint mapping preserves snippets/match offsets despite expanding folds such as ß→ss. The original bytes are not normalized or rewritten. Authenticated scoped GET message-content portions validate the canonical registry identity and agent/session message binding, positive bounded IDs, offset and immutable content revision. Wrong bot returns404; changed revision409. Payload is capped8000 codepoints per portion.

MessageSearch opens at the actual match beyond an8000-character preview, then replaces one bounded read-only portion via authoritative next/previous cursors. It never navigates to another active session, changes unread/pins, clears or submits a composer, or admits work. Late scope/query replies and identity/revision/cursor mismatches cannot render foreign content. The user can inspect complete oversized retained content without a session navigator or accumulating unbounded UI pages.

Evidence: unicode-search-before.log reproduced real SQLite lower('Straße') failing STRASSE with no disk state. message-search-content-ui.log3 passed (late foreign agent, exact large-match offset/portion replacement, foreign response refusal); message-search-content-build.log type/theme/Vite/no-mock pass, external unserved. Backend fixture reads every portion and reconstructs exact original Unicode message, checks scope/revision/overflow/admin-prefix routes and unchanged metadata/no requests. Initial message-search-content-checks.log remains FAILED (2 failed/82 passed): two historical approval tests expected404/reversed-error text. Actual existing owner is first-writer-wins409 and generic stale/missing errors. Tests were strengthened to assert the original resolved decision/row stays immutable and exactly one owned handoff callback occurs; no approval production code changed, and fixture callback excludes model/network work. Final backend outcome recorded below.

Ledger correction from direct source inspection: GB003's shared appearance producer already fixed in a1453efd; tokens and applyAppearance use the same root class. Do not mask or reimplement CSS from an old loaded-app observation; current native/pixel acceptance still pending and production unchanged. GB002's supported templates/configuration implementation is separate from GB041's marketplace/export declarations. Original79 IDs/acceptance criteria retained.

Final search/registry/proxy run: message-search-content-final.log84 passed/24 existing aiohttp warnings after contract assertion repairs. No failure dropped/skipped; earlier failed artifact retained. Owned fixture38566 resumed; production and real-agent/user state untouched. Source build/fixtures do not certify native/browser acceptance.

### GB-063 — atomic model preferences, admission availability and actual identity (source, 2026-10-20)

Existing session metadata now owns a monotonic model_choice_revision. Pointer and control-operation receipt commit atomically; exact session/actor/raw choice/revision fingerprint prevents nonce reuse and duplicate availability probes. Current settings advertise support; old clients retain existing simple PATCH/readback behavior. Atomic metadata merge repairs the prior read-then-write race that could lose unrelated fields. Explicit admitted and queued model/provider changes advance the same generation. Queue promotion preserves frozen execution but cannot restore an old implicit default over a newer explicit conversation setting.

Gateway settings retains a separate per-conversation proposed-model draft and immutable save journal. Unknown ACKs expose read-only original receipt checks, never auto-send/retry. Known conflicts retain proposal and require refresh/review. Explicit reviewed cancellation settles only an uncommitted config intent under the original fingerprint, preventing a late handler from writing; an already committed receipt wins and is never undone. This operation touches no admitted turn/unknown execution/tool, history, credentials or permissions. Malformed/cross-scope receipts cannot clear the journal. Existing PATCH session authorization is turn scope, including jaegerd's already-supported ability, with unchanged prefix/session checks; no new admin gate or privilege change.

Fresh normal admissions revalidate an explicitly selected/saved model against the current existing inventory. Positively observed unavailable catalog entries reject before request/worker creation; unprobed/unknown provider catalogs are not fabricated as available. The session generation is rechecked in the admission transaction to close a validation race. Historical receipts bypass revalidation and do not execute again, including owned execution_unknown fixtures. The real user unknown request remains untouched. Model inventory is stubbed at its existing I/O boundary in tests; no real provider contact.

New turn.model→model_identity durable parts distinguish provider-reported actual ID from Unknown. Direct model responses retain a bounded safe actual-model field where reported; known loaded transport secret and secret-pattern values are suppressed. ReAct routes without a retained provider ID explicitly show Unknown, not the requested name. Legacy result.model remains the configured route and is qualified by model_field_scope; no inference of provider internals or independent identity verification.

Compatibility/rollback before activation: additive session metadata/control rows/events/parts; no DB schema migration. Keep device model draft/pending journals and receipts. Old clients writing through current canonical owners advance generation; binaries predating this code do not maintain that counter or advertise atomic support, so rollback must coordinate outstanding versioned operations and cannot claim cross-version CAS. No user settings/credentials/production processes changed in this coding pass.

Evidence in existing external blueprint root: model-choice-atomic-last.log55 passed/19 existing aiohttp warnings, including real transactional concurrency/ABA/reopen, immutable admitted snapshots, implicit queue preservation, actor-bound duplicates, rejected availability receipt, safe pending cancellation, fresh catalog-loss denial and unknown receipt without worker replay, normal Gateway direct-response actual-versus-unknown model receipts. model-choice-atomic-ui-last.log13 passed; model-choice-atomic-build-last.log theme/type/Vite/no-mock pass (existing chunk advisory), external unserved.

Preserved failed artifacts: model-choice-focused.log1 failed/28 passed because the new test incorrectly expected jaegerd denied on an existing turn-scoped session route; corrected to assert cross-actor nonce conflict, invalid-token401 and foreign-prefix403 without changing authorization. model-choice-admission-final.log1 failed/52 passed because the old exact settings DTO lacked the new generation/capability fields; exact contract assertion extended, not weakened. No failure skipped or counted as pass. Comprehensive provider/browser/native acceptance remains deferred; original popup/native gap and voice/large-avatar exclusions retained. Further coding remains on other open GB packages.

### GB-053 — opt-in bounded transport counters and reviewed export (source, 2026-10-20)

Existing Gateway diagnostics now owns an optional current-process RAM capture: fixed parser/transport/subscriber failure categories, hashed source references, occurrence versus unique receipt counters,128 unique receipts,300-second maximum and1M counter ceiling. Monotonic expiry and same-operation duplicate start never extend consent. Stop/expiry reject later reports. Restart loses volatile counters and never restarts capture. No transcript/request/approval changes, raw frames/errors/headers/prompts, external upload or parallel service/store. Existing read/admin/prefixed caller boundaries remain; source/request correlation validated before hashing. Existing durable unknown visibility retained unchanged.

Shared UI explicitly reviews a60-second browser-profile opt-in. Read status cannot enable reporting; fixed-code best-effort observer never masks/retries execution failures. Device intent persists before command; lost ACK reads original status, process change remains unknown, never repeats start. Sanitized export is previewed locally before explicit download request; native host delivery is not claimed. New capture explicitly replaces only previous volatile metrics. Compatibility: no schema migration; preserve device unknown journals on rollback. Production reporting remains off; no runtime reload/deploy or user traffic collection performed.

Focused evidence external blueprint root: diagnostic-capture-backend-last.log55 passed/3 existing aiohttp warnings; diagnostic-capture-ui.log8 passed; diagnostic-capture-build.log theme/type/Vite/no-mock pass with existing chunk advisory, external unserved. Authenticated local fixture verifies raw/unknown fields rejected, out-of-scope source denied, dedup/expiry/bounds, export contains no fixture secret/prompt/identities, unchanged request and global events. Failed backend artifacts diagnostic-capture-backend.log and diagnostic-capture-backend-final.log preserved: initial fixture incorrectly compared pre-startup admission (legitimate recovery changes it) and empty global stream despite legitimate admission event; final baseline captured after startup/admission, exact immutability checks retained. Owned idle fixture38566 resumed. Full native/browser opt-in/download acceptance deferred; prior popup/native visual gap and paused voice/large avatars unchanged.

### GB-038 — in-progress schedule timezone/revision compatibility (source only)

Planned existing state.db schema7 adds nullable schedule timezone and monotonic config_revision. NULL preserves legacy Gateway-local recurrence; explicit IANA zones use ZoneInfo for future occurrences and UTC storage. No existing row/timezone/next run is rewritten. Older schema6 binaries deliberately refuse newer state.db; rollback requires retaining schema7-aware owner or restoring a pre-activation isolated backup, never changing the version stamp. No production migration authorized/performed. New UI will preserve an open editor revision and reject stale writes; existing clients may keep their existing owner contract without CAS. Unknown control operations remain inspect-only, never automatically repeated.

GB038 source landed in the existing owner: explicit IANA zone validation and persistence, ZoneInfo recurrence through create/update/due-claim, UTC storage, nullable legacy Gateway-local policy, monotonic config revision and atomic stale-update rejection. Fixed actual next-run projection mismatch (owner next_run_at→typed next_fire_at). UI displays saved execution zone and UTC occurrence, and submits the open editor's original revision. Run now retains existing control receipts/task approval boundaries and leaves recurrence unchanged. Source-only schema7 migration, no production changes.

Focused evidence: schedule-timezone-backend.log39 passed/5 existing warnings (real prior-shape migration, legacy values unchanged, spring/fall9am UTC offset change without duplicate due claim, invalid zone/stale revision rejection, same run intent→one task/unchanged recurrence, prior control recovery regressions); schedule-timezone-ui.log2 passed; schedule-timezone-build.log theme/type/Vite/no-mock pass external unserved. Full real DST scheduling/browser/native/model acceptance deferred. Owned idle fixture38566 resumed. No proprietary timing semantics or all ambiguous/nonexistent wall-hour behavior certified by these bounded9am fixtures.

### GB-034 — durable task presentation and truthful board states (source, 2026-10-20)

Existing Gateway schema_meta/control_operations now own independent operator task pin, explicit unread/read watermark and to-do done/reopen metadata. Exact actor/task/action command fingerprints, task updated_at plus presentation revision CAS, and metadata+receipt commit in one transaction. Duplicate commands return historical receipt without undoing later checklist/read state; known conflicts do not alter the task. Worker saves cannot overwrite presentation because execution task_json is untouched. No new DB/schema/service, permissions or execution authority. Rollback retains additive metadata and device journals; old clients ignore presentation. One existing local-operator scope, no invented cross-account/team sharing.

Board fixes actual completed/completed_verified fall-through: both appear Finished with failed/cancelled and exact status/failure details retained. Details show stable task/origin/request/run receipts and last observed timestamp; polling is not represented as live progress. Pin ordering stays within authoritative state columns. Explicit to-do done is a separate checklist, never verified execution; owner-terminal blocked/needs-owner cancellation is not falsely offered. Per-task UI journals before HTTP, preserves uncertain intent across remount, queries only the original scoped receipt and refuses foreign/incomplete success. Real approvals/cancel/worker owner unchanged.

Focused evidence external blueprint root: task-presentation-backend.log60 passed/8 existing aiohttp warnings, including real authenticated routes/SQLite state, immutable task/error/provenance/authorization, duplicate pin after later to-do change, stale task/read conflict, missing/cross-actor/foreign-operation scope, worker-save preservation, new result becomes unread, reopen/read receipt without repeat. Fixture runner startup stubbed deliberately: these tests do not prove task execution. task-presentation-ui-final.log8 passed; task-presentation-build-final.log theme/type/Vite/no-mock pass external unserved; prior UI7-pass artifact retained. No production/user task changes, provider calls or deployments. Full execution/browser/native acceptance deferred; existing popup/native gap and paused media exclusions preserved.

### GB-013 — literal spreadsheet previews through verified attachment reads (source, 2026-10-20)

Existing conversation file reader now supports view=preview for bounded XLSX/CSV/TSV literal cells. It first verifies session/registered file/digest/current originating workspace with the same no-follow reader. No new access route, dependency, DB/schema, renderer worker or external application. XLSX parsing caps compressed input, expanded archive, part count/size/ratio, shared strings, sheets/rows/columns/cell text; encrypted/ambiguous/malformed/XML declarations fail to unsupported fallback. No archive extraction, formula evaluation, macro execution or external relationship fetching. Cached values are labeled potentially stale/truncated, sparse row numbers retained. Original raw-byte download remains separate and hash-verified. PDF/rich office renderers remain code work; no fake PDF preview claimed.

UI validates bounded derived DTO, exact session/attachment/digest/size/name/MIME and generation; selecting a second preview discards a late first response. Literal HTML/formula cells mount only as React text. Existing object URLs are released and unsupported formats retain explicit verified-download fallback. No preview read is model admission, attachment selection or transcript/read-marker mutation. Rollback requires no migration; existing registered bytes untouched. No real user files or production changed.

Evidence: spreadsheet-preview-backend.log57 passed/3 existing warnings; final affected attachment access/task presentation/diagnostics run spreadsheet-preview-affected-final.log7 passed/6 existing warnings after last backend edits. spreadsheet-preview-ui-final.log4 passed; spreadsheet-preview-build-final.log theme/type/Vite/no-mock pass external unserved. Initial spreadsheet-preview-ui.log1 failed/3 passed preserved: existing real WebCrypto test asserted before asynchronous digest settled; bounded1s assertion wait added, exact bad-digest rejection retained. Real synthetic upload→registered hash→read-only spreadsheet projection verified; changed bytes/cross-session/prefixed access rejected. Source fixtures are not native download, model or comprehensive browser acceptance. Owned idle fixture38566 resumed; prior popup/native visual and paused media limits retained.

### GB-012 — resumable immutable byte staging and pre-dispatch progress (source, 2026-10-20)

Large byte attachments now use authenticated descriptor→256KiB immutable chunks→final SHA/size verification→existing attachment registration. Descriptor/caller/session/operation lives in existing Gateway schema_meta; partial bytes under canonical external staging root. No new DB/schema/service, no model request or automatic attachment admission. Equal repeated chunks are harmless; changed/gapped/oversize chunks fail. Writes link atomically after fsync; read status discovers a crash/lost ACK after retained bytes without replaying that chunk. Finalize reuses the existing byte-upload/idempotency producer; a lost final ACK resolves to the same attachment. Partial bytes are never present in selectable attachment rows; only exact finalized IDs enter immutable turn admission. Regular/no-follow bounded chunk reads reject fixture symlinks.

Typed client keeps descriptor/nonce/acknowledged upload ID only in device recovery storage, not raw bytes. It validates original source/digest/progress and uses status after lost ACK. Explicit re-invocation with the same selected bytes resumes retained progress; a previously acknowledged but now missing manifest remains unknown rather than inventing a new identity. A pre-commit unacknowledged descriptor may be recreated via the same inert atomic descriptor command, never a turn/tool/approval retry. No uncertain real execution request is replayed. Original small-file/path contracts retained. Stream shows actual staged-byte counters before turn dispatch, without claiming that bytes were model-consumed.

Stop during preparation aborts only the upload HTTP signal; it does not abort the independently owned execution observer. If a turn's admission is already in flight, existing Stop waits for its authoritative receipt/cancellation. No turn dispatch after a preparation Stop; original drafts and partial byte files retained. Progress observers cannot alter staging outcome. No production/user-file/model/provider activity. Compatibility: additive metadata/files only, old sources ignore pending manifests, finalized attachments keep original canonical contract. Preserve partial files and device journals on rollback; automatic partial-file cleanup/permanent deletion is intentionally absent under current scope.

Focused evidence external blueprint root: chunk-upload-backend-final.log82 passed/5 existing warnings; final scope assertion chunk-upload-scope-last.log2 passed/4 warnings. Real HTTP/SQLite original descriptor/reopen, identical/different chunks, incomplete/bad-hash finalization, exact final bytes/read/admission, no pending or implicit staged inheritance, cross-session/caller/prefixed/admin checks, retained fixture bytes after symlink refusal. Admissions only, no model execution. Initial chunk-upload-backend.log1 failed/81 passed preserved: test attempted a second admission without settling the first; now cancels the owned unexecuted fixture through canonical complete_request, preserving busy guard.

UI evidence: chunk-upload-ui-final.log38 passed; after final source refinement chunk-upload-ui-source-final.log25 passed (5 chunk,6 recovery,14 follow-turn/Stop), chunk-upload-build-source-final.log theme/type/Vite/no-mock pass, external unserved. Other passing intermediate logs retained separately, not summed into unique coverage. Full native/browser/model acceptance deferred; popup/native visual gap and paused voice/large avatars unchanged. Idle owned fixture38566 resumed. No whole-app readiness or loaded-production claim.

### GB-035 — child model controls and durable owner/follow-up admission (source, 2026-10-20)

Tasks now offers existing origin/home→advertised canonical native specialist with configured model or existing routing. Work is accurately durable background; no fake foreground toggle or permission elevation. Requested model resolves through existing inventory for a new intent and is immutable in handoff metadata/child admission; target registry role/tools, parent defaults/context and caller actor remain unchanged. Actual provider identity remains a separate truth contract. Approval shows requested model. Original approval/project standing-grant behavior retained. Unsupported foreground/permission overrides refuse explicitly, and disabled/missing targets fail at the routing producer before a child starts; old original admission receipts remain inspectable.

Owner commands reuse existing control_operations before existing handoff admission. Exact caller/resource/body identity, durable saved/rejected outcomes and fingerprint-qualified admission proof after lost ACK; uncertain reservation never reruns its handler. Known model rejection cannot become execution after catalog changes. Alternate legacy POST cannot replay the retained owner command. No new DB/schema/service or security/auth change. New routes retain admin, Stop/live-owner and prefix gates. Original model delegate route remains available under its existing scope.

Follow-up dialog now preserves device draft/original nonce across close/remount, locks uncertain resubmission and queries the existing exchange's original command. Exact command body and row/thread/session identity qualify both success and rejection; foreign/incomplete receipts cannot clear journal. Only the accepted original draft is consumed; newer text remains. Replies inherit the original requested model but always retain their existing new-approval requirement and tools ceiling. Incoming bot data never authorizes execution. No session list/navigation redesign or popup/voice changes.

Compatibility: additive existing handoff metadata/control rows and device journals only. Keep unknown reservations/journals on rollback; do not repeat through an older alternate route. Partial wrapper ACK can be proven from a matching canonical handoff, without new admission. One local operator with existing per-surface actor attribution, not invented accounts/teams. Real user agents/drafts/history, credentials and production processes untouched.

Focused evidence: handoff-options-backend-final.log77 passed/18 existing aiohttp warnings (real HTTP/SQLite command paths and proxy/legacy regressions); handoff-options-owner-last.log22 passed/20 warnings after Stop/lease/disabled producer guards; handoff-options-contract-last.log6 passed/8 warnings after explicit unsupported permission/foreground validation. Model inventory/execution callback deliberately fixture-stubbed: tests assert the real admitted model/provider/caller/tools/is_subordinate snapshot, not paid model/tool execution. Concurrent same command→one handoff/approval; known rejection stable after inventory change; original reply has exact parent/thread/tools/model, no parent/registry mutation; lost wrapper ACK recovers existing child; Stop/offline lease creates no reservation/admission. Earlier passing artifacts retained separately, not summed as unique coverage.

UI handoff-options-ui-last.log12 passed; handoff-options-build-last.log theme/type/Vite/no-mock pass external unserved. New request selection/model journey, preserved newer draft, original-only receipt recovery and rejection body correlation covered. No production deployment/native acceptance. Existing popup/native visual gap remains.

GB035 still code_remaining: general parent-turn→owned handoff cancellation outside bridge-specific cancel_handoffs, plus explicit owned handoff cancellation control/receipt. Canonical parent linkage must be validated before cascading, preserving foreign, independent and execution_unknown work. Existing bridge cancellation is not whole-group proof. This is implementation work, not an external blocker. Continue that dependent slice; full actual child execution/browser/native campaign remains deferred. Voice/large-avatar exclusions retained; original79/316 proposed criteria untouched.

GB035 post-commit lint correction: the broader new-module Ruff check found14 issues beyond the previously passing F821/E9 check (import/pytest fixture exposure, mutable request class attribute, type-error convention and intentional unknown-outcome catch). Preserved handoff-options-lint-before.log FAILED; corrected source uses standard pytest_plugins fixture loading and per-instance match_info, sorted imports and TypeError. The intentional broad catch is explicitly documented because unexpected post-admission errors must remain unknown, never be retried. handoff-options-lint-after.log PASS; after those edits handoff-options-lint-fixture-last.log6 passed/8 existing warnings. No test removed/skipped or business condition weakened. Source only; GB035 parent cancellation code remains open.

### GB-035 — canonical child receipt recovery dependency (source, 2026-10-20)

Direct inspection found current unknown-handoff GET only consulted retained native receipts while current children are admitted in Gateway client_requests. It now qualifies the existing canonical child using the shared deterministic ID, exact specialist session/handoff/agent, subordinate flag and original caller. Only retained completed/failed/cancelled receipts settle and post the existing result; repeat read does not duplicate parent posts. Current admitted/running/unknown and foreign-binding records stay unknown without consulting a different owner or executing. Foreign child output withheld. Recovered scope explicitly child-request outcome; no goal verification inferred. No new admission/approval/tool call.

Added contract/handoffs.py as the single digest/child-ID definition, preserving both old64-character retained native read correlation and current32-character Gateway IDs byte-for-byte. Gateway execution, read recovery and bridge-origin validation import it; former feature helper removed and its importer repointed, no compatibility re-export. Historical native receipt read remains only when no current child exists; no old frontend/runtime/service fallback is started. No schema or state migration, no real unknown-request replay or production change.

Evidence: handoff-receipt-recovery.log24 passed/22 existing warnings; after final helper import/assertion/result-scope edits handoff-receipt-recovery-final.log6 passed/7 warnings, including existing selected bridge goal-spoof/forged-child fixture. Real owned store receipts, authenticated reads, all three terminal states, duplicate reads, unknown preservation and foreign-result withholding. Exact real child/model/browser/native execution acceptance remains deferred. New contract/test full Ruff and affected source F821/E9 pass; an initial unused fixture-variable lint finding was repaired by stronger session-identity assertions, not suppressions. Idle fixture38566 resumed. General parent cancellation remains code work; canonical receipt lookup is now available for that implementation.

### GB-021/022/035 — Stop preserves uncertain outcomes and exposes actual acknowledgement (source, 2026-10-20)

Causal isolated reproduction unknown-stop-before.log FAILED1: authenticated Stop changed an existing execution_unknown to cancelling, erasing its recorded uncertainty before any new effect proof. Producer fix in GatewaySessionStore.mark_request_status now refuses only that transition; original unknown receipt/result/timestamp remain, while the existing cancellation scope can still be signalled. Ordinary admitted/running cancellation behavior retained. No new execution, approval grant, schema or data migration. This does not physically reconcile an uncertain effect or claim a stopped process.

Typed GatewayClient.cancel now returns actual acknowledgement rather than discarding it. WebHost checks its original session/request and warns when outcome remains unconfirmed, keeping the original observer active. Late acknowledgements do not append a false waiting message after observation ended. Terminal settlement still comes from canonical events/receipts, not an ACK/EOF. Source contract can display backend-reported owned IDs; actual general descendant enumeration/cascade is still code_remaining under GB035, not silently counted implemented from a synthetic field.

Evidence: unknown-stop-after.log17 passed/13 existing warnings, then unknown-stop-contract-last.log2 passed/4 warnings after explicit ordinary-admission regression added. Exact unknown result/status/timestamp and unrelated request preserved; no worker invoked. unknown-stop-ui.log29 passed, unknown-stop-build.log theme/type/Vite/no-mock pass external unserved. UI child-ID warning uses a supplemental source fixture; actual backend currently returns root acknowledgement only. Do not call that a real descendant stop proof. Existing physical sleeping-process evidence is separate and does not close general cancellation scope. Idle fixture38566 resumed; no actual user request/draft/metadata, production or real unknown request touched.

Ledger correction: GB021 now code_remaining for actual descendant enumeration/cascade, coordinated with GB035. Prior acceptance-only classification was too broad for A4. GB022 retains implemented unknown/recovery slices awaiting real acceptance. No comprehensive campaign, deployment/native reload, old app fallback, credentials or network changes.

In-progress GB021/035 cancellation compatibility before activation: additive producer-qualified parent_binding and monotonic cancel metadata in existing handoff rows, no schema migration. Historical unqualified relationships are retained and not guessed into cascade authority. Rollback must retain an aware metadata writer while cancel intents are pending; older writers can lose new monotonic flags. No production records modified or runtime switched. No cancellation is proof of arbitrary process cleanup or goal verification; current child receipts remain authoritative for their own scope.

### Owned handoff Stop/cascade source checkpoint — 2026-10-20

Implemented GB021/035 within existing request/handoff/cancellation owners. New handoff parent bindings derive immutable root request, source agent, session and authenticated caller (not display name, primary pointer or body chain). Existing receipts retain their original identity. Parent Stop walks qualified canonical children including completed/failed/cancelled intermediate requests; active/unknown grandchildren remain visible and unconfirmed. Foreign receipt bindings never signal another scope or reveal its result. Historical unqualified links report their retained handoff IDs without inferred authority. Request terminal receipts are unchanged; execution_unknown cannot become cancelling/cancelled from an acknowledgement. Canonical child truth takes precedence over stale terminal handoff labels/pre-admission hints for every status.

Existing handoff metadata owns monotonic cancellation intent. Pending/approved/admitted handoffs with no canonical child cancel atomically before admission and close only corresponding approvals. In-flight admission rechecks cancellation after awaited model availability. Stale worker saves cannot drop intent or overwrite terminal cancellation; final handoff outcome uses qualified canonical receipt, not a successful transport/Stop flag. Existing bridge goal cancellation uses the same implementation and exposes owned/unconfirmed IDs. Tasks now exposes latest100 existing specialist records, actual current child status and explicit Stop; local journal precedes dispatch, lost acknowledgement permits original-receipt reads only. Parent observation finishing before the cancellation reply no longer loses descendant warnings. Closing/navigation never cancels admitted work implicitly.

Compatibility/recovery: no new schema/store/service. Additive parent_binding/cancel_requested metadata and existing control_operations; retain cancellation-aware reader/writer while intents are outstanding. Do not roll back to an old writer that ignores these intents. Preserve external attachment/state stores and device jaeger.ui.handoff-stop.v1 journal. No historical relationship rewrite, transcript deletion, approval grant, runtime restart, production migration, user draft/metadata change or uncertain-effect replay.

Focused evidence under ~/.cache/jaeger/verification/blueprint-20261020/: handoff-cancel-controls-third.log **27 passed**,29 existing aiohttp key warnings. Owned fixture covers stale completed/cancelled label plus active/unknown child, complete/failed/cancelled intermediate plus unknown grandchild, unrelated/foreign scope untouched, repeated interruption once, pending approval closed/no child, stopped parent refuses new child, model-discovery race/no admission, sticky stale save, owner/admin/prefix guards, immutable Stop reservation/lookup, canonical receipt recovery and original unknown preservation. Real local scripted-tool bridge fixture waits for canonical child cancelled and retained handoff cancelled, checks no cancelled-team.txt before/after, no pending approvals; no external provider or connection. This is actual isolated backend/tool evidence, not installed/native acceptance.

UI handoff-cancel-ui-first.log **30 passed** (OwnedHandoffs2, SpecialistHandoff4, TasksBoard6, HandoffReplyDialog2, followTurn16). handoff-cancel-build-second.log type/theme/Vite/no-mock pass; external unserved build, existing chunk warning. Earlier first/second backend failure artifacts preserved: fixture expected approval label denied instead of actual resolved/decision=cancelled, nested target re-entered ancestor (correct loop rejection), attempted fixture mutation of immutable model choice (correctly ignored), and immediate cancelled label expectation before child settlement. Tests now require actual receipt/effect truth without relaxing guards. First build rejected test global typing, corrected; failed log retained. Source lint new modules/test full Ruff pass and existing changed sources F821/E9 pass. Comprehensive real model/browser/native campaign remains deferred; no whole-app readiness claim. Existing popup/native pixel acceptance gap remains; voice/large-avatar exclusions unchanged.

Final affected UI source check: handoff-cancel-ui-source-final.log **31 passed**; OwnedHandoffs adds known pre-execution auth/Stop/lease rejection without a fake cancellation or trapped unknown intent. Lost/ambiguous acknowledgements still retain exact original intent and never replay. handoff-cancel-build-source-final.log external unserved theme/type/Vite/no-mock pass. Backend last edit remains covered by handoff-cancel-controls-third.log27 passed. New source/test full Ruff, existing edited-source F821/E9, git diff --check and ledger79/unique IDs/exclusions/LF checks pass. No full acceptance or broad verification rerun claimed; coding-first instruction defers that campaign.

#### Stop proxy connection correction

Post-checkpoint route inspection found the new leaf Stop/state/list/original routes absent from the WebUI allowlisted proxy. Causal handoff-stop-proxy-before.log has4 failed exact-route assertions. Added exact GET/POST mappings preserving body bytes and existing server-side caller authentication. handoff-stop-proxy-after.log **61 passed** (affected proxy module including4 new routes); existing edited files F821/E9 and diff checks pass. These route fixtures prove adapter/proxy dispatch, alongside27 earlier real isolated Gateway tests; they do not prove installed/live UI. This corrects a disconnected control before any deployment; production remains unchanged.

### GB040 recoverable playbook lifecycle slice — 2026-10-21

Implemented owner-backed reviewed remove/restore for existing instance playbooks, shared UI → typed adapter → authenticated WebUI proxy → existing SkillService → whole-folder move/retained assets → existing Gateway control receipt → visible status. No replacement catalog/store/runtime. Canonical shared active-path guard excludes hidden archive/staging trees and symlink aliases from actual model-facing playbook discovery/signature and management readers. Archive collisions preserve both versions instead of deleting prior assets. Same-zone duplicate names refuse management rather than choosing a different folder from runtime discovery. Code+playbook skills advertise management unavailable in this panel; no hot unload claim, bundled protection retained. The lower-level legacy service reports restart-required for code companions.

Remove accepts the exact reviewed complete-folder revision at the owner. Managed install/clone, archive/remove and restore serialize on the existing instance archive lock. Revision is checked again under that lock immediately before the atomic move; a replacement arriving between Gateway review and mutation is rejected and remains active. No downstream cosmetic version compensation. Restore checks exact retained content and origin-relative path, preserves asset modes, refuses changed archives/active replacements and can read an already-restored identical result. No script import, tool grant, config permission change, external install, package activation or publication performed.

Existing control_operations owns actor/body-bound saved/rejected/unknown receipts; repeated commands/lookup do not rerun filesystem mutations. Device jaeger.ui.skill-change.v1 journal precedes POST, original lookup never resubmits and receipt validates exact command/body, action, operation and result. Review/confirm separate from clicking a catalog row; known pre-execution rejection is honest, ambiguous acknowledgement retains original intent. Read-only refresh supported. Catalog/receipt text is redacted through the existing loaded-secret redactor. New GET/POST routes preserve existing admin/owner, prefixed peer, Stop and live-owner guards.

Compatibility/recovery: no DB schema change. Existing instance skills/.archive receives whole original folders and an internal serialization lock; prior archives are never overwritten/purged. Archive/staging-aware readers must remain during rollback; old recursive scanners can rediscover retired playbooks. Preserve device journal and existing control_operations. If the process fails after the folder move but before durable receipt completion, the reservation remains unknown and the archive is retained; automatic reconstruction/compensation for that exact filesystem/SQLite crash window is still code_remaining. No replay or fake successful recovery. No actual user skill, conversation/draft, production process, real unknown request or security settings changed.

Focused source evidence under existing blueprint-20261020 directory: skill-recovery-controls-final.log **107 passed**,5 existing aiohttp key warnings, covering owner/service/playbook/maintenance/proxy fixtures. Includes deterministic edit after Gateway check and a second edit while acquiring the archive mutation lock; both reject and preserve active replacement, retained rejection never later executes. Also original assets/modes, changed archive, occupied target, collision preservation, hidden/symlink discovery, duplicate identity, code companion protection, scoped admin refusal, original receipt/unknown no replay and actual isolated folder remove/restore. Earlier skill-retirement-foundation-first.log36 passed, skill-recovery-owner-first.log38 passed and skill-recovery-controls-first.log103 passed pre-final edits are supplementary only. skill-recovery-ui-source-final.log **4 passed**; explicit remove/recovery, restore review and foreign-body rejection plus existing metadata test. skill-recovery-build-source-final.log theme/type/Vite/no-mock pass, external unserved; existing chunk advisory remains. New route/test full Ruff, changed existing sources F821/E9 and git diff --check pass. Comprehensive real browser/native/model acceptance remains deferred; not production/whole-GB completion.

Exact GB040 code remainder: safe local import/update/version rollback controls and original provenance/export/publishing policy remain, plus the exact post-filesystem/pre-receipt crash reconciliation above. External publisher activation/upload needs separate authorization; absence of these source controls is implementation work, not an external blocker. Other ledger rows retain their existing code/acceptance/exclusion state. Voice/large avatars and popup/native visual acceptance gap preserved.

#### GB040 move/receipt crash reconciliation — 2026-10-21

Closed the identified post-move/pre-receipt source gap: existing schema_meta stores an actor/command/fingerprint/current-instance-bound precommit move plan while the existing skill lock is held. Only then may the producer atomically rename. Original operation lookup compares exact active/archive paths and full content revision; proven remove/restoration can settle the existing control receipt without calling a mutation again. A planned but unproven move, changed/missing content, foreign instance, corrupt plan or legacy reservation without a plan remains unknown. No inference from assistant text or receipt absence; no automatic rename/compensation/retry. Per-resource existing scoped control reservations block fresh commands behind uncertainty. A newly blocked command receives its own durable rejection without changing the outstanding resource pointer, so it cannot become executable after a later recovery.

Archive identities and managed origin paths use shared owner validation; unsupported ambiguous/deep/noncanonical paths refuse removal before moving anything. Existing active replacements, no-follow assets and caller/admin/Stop/lease guards unchanged. Recovery adds only metadata keys in the same existing Gateway DB; no schema/new store. Rollback must retain plan/resource-aware owner while outstanding operations exist. Old unplanned/ambiguous outcomes remain visible unknown and require inspection; this is truthful retained uncertainty, not a fabricated completion or replay permission.

Evidence: skill-plan-recovery-final.log **23 passed**,7 existing warnings (service/owner/maintenance). After the last durable-rejection edit, skill-plan-recovery-source-final.log **5 passed**,7 existing warnings (all affected authenticated owner journeys). Fixtures inject failure after actual remove and restore but before receipt storage, then prohibit both mutation functions: read-only lookup recovers saved exact identities and repeated POST returns the same receipt without execution. Another fixture interrupts after plan/before move: active bytes survive, original stays unknown, fresh commands are durably rejected and never enter the owner. Previous full107 source/proxy and UI4/type/build evidence remains distinct; this backend-only follow-up does not change built UI bytes or perform live acceptance. Full new route/test Ruff, changed existing F821/E9 and diff checks pass. Fixture worker resumed; no production/app/draft/user memory/credential change or real unknown replay.

GB040 code_remaining now: reviewed local import/update/version rollback and provenance/export/publishing policy. The bounded move/receipt crash window is implemented awaiting broader acceptance; arbitrary ecosystem/native package parity is not added. Other79-row classifications and paused exclusions unchanged.

### GB040 reviewed local import/update/version slice — 2026-10-21

Implemented shared Skills editor → owner review → exact digest/version confirmation → existing SkillService → existing registry → existing receipt/history. Original owner-provided Markdown only: no external fetch, package/code import or publication. The real owner validates matching frontmatter/canonical path, refuses bundled/code identity shadowing, critical safety findings, potential credential material, occupied destinations and stale whole-folder revision. Updates retain a verified complete prior file/asset snapshot in the existing archive; current assets stay intact. A previous version can be restored only after explicit reviewed removal of the active copy, so rollback cannot silently overwrite newer work. Declared version/provenance is labeled unverified; actual content revision is shown. Requested/new tool requirements are visible at review, scope_granted=false, existing tool ceilings/approvals/config remain unchanged.

Existing move-plan/control owners now also recover exact installed/updated state after a saved-file/pre-receipt crash without invoking save again. Save command receipts/plans persist only content hash/byte count, not the Markdown body; control identity still binds exact content. File staging moved outside the active folder, so a staging file cannot perturb its reviewed revision. Remove/save/restore revalidate immediately after durable planning and directly before replace/rename under the shared mutation lock. Deterministic planning callbacks that edit source cause rejection and retain the replacement. Bounded regular-file snapshot reading caps files/entries/bytes, rejects symlinks/hardlinks/devices/special permission bits and preserves prior content-revision path ordering (compatibility test).

The editor retains unsent drafts, asks before replacing editor text, preserves newer other-window edits after an older save acknowledgement, validates exact review/body digest and never saves before explicit confirmation. Redacted content is a durable read-only projection, including after reload. An instance-copy removal is explicitly distinguished from an installed bundled fallback remaining available. Publish/unpublish availability policy is still separate code work; no false global-unpublished claim.

Evidence in existing blueprint-20261020 external directory: skill-import-wiring-final.log **87 passed**,10 existing warnings (owner/service/proxy including exact review/content routes and actual local file/version effects). After last producer revalidation/tool-delta edits, skill-import-owner-last.log **31 passed**,10 existing warnings (all affected owner/service/maintenance paths). Covers reviewed import/update, stale conflict, explicit remove/old-version restore with assets, built-in/critical refusal, configuration/grant bytes unchanged, full revision compatibility, actual post-save crash recovery with save prohibited, repeated command/unknown fences and concurrent replacement protection. Prior skill-import-owner-source-final.log30 and wiring-first.log85 are supplementary pre-final evidence. skill-import-ui-final.log **7 passed**, including review→confirm→single save, digest-only receipt, newer draft preservation, readonly-redaction reload and existing remove/restore/foreign-body checks. skill-import-build-final.log theme/type/Vite/no-mock pass, external unserved; existing chunk advisory remains. Earlier build-first/second logs failed receipt-union narrowing and one stale variable; both corrected without weakening checks. New route/test full Ruff, edited existing F821/E9 and git diff --check pass.

No production restart/reload/deploy, real-user skill/memory/draft mutation, new credentials/grants, external activation/send or unknown execution replay. Runtime still loads prior deployed source. Comprehensive live browser/native/model acceptance remains deferred and the popup/native pixel gap remains open. GB040 exact remaining code: explicit local publish/unpublish availability policy through the existing skill configuration owner, export/publish-target policy and provenance presentation; actual external publisher activation/publication requires separate provider/authorization. Other GB rows and voice/large-avatar exclusions unchanged.

#### GB040 local export target — 2026-10-21

Implemented exact-revision owner-only local data-bundle export through SkillService/Gateway/authenticated proxy/typed adapter/Skills control. Actual regular-file bytes and individual hashes, original instance provenance explicitly unverified, publisher/license verification false. No remote publisher, code activation, package extraction or external send. Export refuses stale selection, hidden/private credential filenames before opening them, symlink/hardlink/special files, unrecognized binary formats, dangerous text and loaded-secret material (including binary text inspection). Browser validates identity/policy/path/size/base64/digests before a JSON Blob; it never interprets exported HTML/SVG/scripts. Navigation/source retirement discards late results. UI requests a local file and explicitly leaves OS save completion unknown. Configured availability and actual content revision are visible separately from declared origin. No global-unpublished claim or grant change.

Evidence: skill-export-backend-final.log **91 passed**,10 existing warnings (current owner/service/proxy). Includes actual authenticated export of restored retained fixture bytes/assets plus admin refusal, stale/private-file refusal and exact proxy query. skill-export-ui-last.log **9 passed**, including member identity/path/content validation and actual component→typed source→Blob/download-request wiring, with OS delivery explicitly unconfirmed; earlier8-test and first9-test artifacts supplemental. skill-export-build-last.log theme/type/Vite/no-mock pass external unserved, existing chunk advisory. The prior source-final build failed test-mock argument typing; fixed and final check passed. New modules/tests Ruff and edited existing F821/E9/diff checks pass. Still no actual native/browser/OS download acceptance or production deployment.

GB040 remaining source: explicit local publish/unpublish availability controls through the existing configuration owner. Existing legacy set_skill_enabled and catalog setters do whole-Config load/dump; coherent revision/CAS mutation is needed before exposing an additional policy writer safely. This is in-repo code work, not an external blocker. External publishing has no configured Jaeger handler/provider contract and remains unsupported, not an inferred proprietary RPC or request for credentials. Local export target is real; arbitrary publisher ecosystem work is not added. Other ledger code groups/acceptance-only gaps/exclusions unchanged.

### GB040 local publish/unpublish and shared configuration producer — 2026-10-21

Implemented reviewed local availability controls using the EXISTING skills.disabled_playbooks policy, not a parallel visibility store. Instance playbook + current content revision + current Config revision + explicit boolean + owner/admin scope required. Disabled code companions/bundled identities cannot use this control. Existing SkillService policy transform does not add tools/base skill grants; future explicit lookup and normal playbook selection actually exclude unpublished names. Current admitted/background work keeps its snapshot. The shared UI distinguishes configured availability, source copy removal and declared provenance; it does not equate an instance-copy removal with globally unpublishing a bundled fallback.

Required producer repair: core/instance/atomic_files.py owns stable per-document locks outside source trees, unique staged files, preserved existing file mode, file/directory fsync, bounded busy wait and compare-before-replace. Schema serialization delegates IO there. Existing catalog settings, model/fallback/onboarding configuration and skill-policy owners now apply targeted validated transforms to a fresh locked document instead of committing stale whole-Config snapshots. No Config/auth fields or permissions added. Independent ordinary field changes coexist; hand-edits during planning reject before replacement. Strict Config extra-field validation remains unchanged; an invalid document is refused with its bytes preserved. The generic helper retains unrelated raw fields only for model types that already accept them. Explicit low-level dump remains full replacement, not an inferred merge. Helpers are independent of new schema exports to avoid coupling lazy readers to an already cached schema generation.

Existing control plans/receipts bind policy content + config revision and recover only proven actual policy state after receipt loss, without calling a setter again. Exact config/content divergence remains unknown; no optimistic success, replay or automatic merge. Existing shared per-resource unknown fence and durable rejected commands remain. Actual config file is the authority, metadata only evidence/receipts. Rollback retains operation plans, scoped pointers and aware owners while pending commands exist; new stable locks under operator_state_root/run/schema-write-locks contain only path digests, never runtime data in repo. No schema/database migration; ordinary changed YAML keeps existing normalization behavior; unchanged documents retain exact bytes. Existing file modes retained, new files private by default.

Evidence: config-policy-owner-last.log **76 passed**,11 existing aiohttp key warnings across atomic config/Settings catalog/Model config/Skill owner/service/schema contracts. Includes actual concurrent independent field writes and preserved mode, stale/CAS rejection, manual-edit preservation, strict-schema refusal, permissive-model raw field preservation, owner-only local publish/unpublish → actual model-facing find_playbook disappearance/restoration, full config/grant comparison and post-config-write lost-receipt recovery with setter prohibited. Earlier first log failed a NEW fixture's nonexistent context_length field; corrected to actual model.ctx. Prior final log failed a NEW assumption that Config permits unknown fields; corrected to assert existing extra_forbidden refusal rather than weaken validation. Both failed artifacts preserved separately. skill-policy-ui-final.log **10 passed**, review/confirm with both revisions and no grant plus earlier lifecycle/editor/export checks. skill-policy-build-final.log theme/type/Vite/no-mock pass external unserved; chunk advisory retained. New helper/routes/tests full Ruff, existing edited-source F821/E9 and diff checks pass.

Bounded GB040 source now supports Jaeger local installed/available/unpublished, reviewed import/update/conflict, retained prior version/assets, recoverable remove/restore, provenance/hash, local export target and no-grant tool-delta visibility. These are implemented_awaiting_acceptance, NOT whole-app or native/live certification. External publisher handler/provider contract is not configured; no proprietary server semantics are inferred and no credentials/provider activation/publication performed. No production restart/reload/deploy or real user skill/config/draft/metadata change; no uncertain real request replay. Popup/native screenshot gap and paused voice/large-avatar scope remain.


### 2026-10-21 — GB-043 disabled setup and durable startup source checkpoint

- Same canonical owner, no runtime rollout. Existing `core/mcp/service.py` now stages NEW URL/command definitions disabled and changes ONLY an existing `enabled` startup flag through shared JSON file-lock/raw-revision CAS. Existing headers/credential references, tool gates, scopes and unrelated config remain byte-value equivalent; new definitions retain gating and no read-only grants. No credential resolver/migrator or transport initialization invoked. Local catalog returns whitelisted metadata, omits command/URL/env/header values, suppresses known-secret identities, and says `not_probed`.
- Existing authenticated owner/admin (no session prefix) HTTP routes `/v1/runtime/mcp/configuration`, `/change`, `/operations/{id}`, exact WebUI proxy mapping, typed adapter and Tools → MCP setup/startup UI. Review precedes confirmation. Future-startup enable warning explicitly says command/remote contact may happen at next MCP initialization; live connection is unchanged. Device original-operation journal survives reload. Unavailable journal prevents dispatch. Server existing control_operations/schema_meta store digest-only intent/plan; matching raw saved hash can recover lost ACK without executing; diverged saved state remains unknown and fences fresh nonces. No schema migration, parallel registry/store or credentials UI.
- Compatibility/rollback: existing instance `mcp.json` fields (`enabled`, `tools.gated/read_only`) and current parser; no new schema. Keep config and original receipts/journal on rollback. Current loaded bridge/config remains untouched; no hot reload, provider contact, user-runtime package execution or production metadata write. Legacy whole-document CLI configuration writers retain legacy semantics; this is not a claim they all became versioned patch APIs.
- Evidence under `~/.cache/jaeger/verification/blueprint-20261020/`: `mcp-startup-backend-final.log` **81 passed,4 warnings** (local JSON/CAS, disabled-before-credential parser boundary with inert registry, secret metadata, lost ACK, existing loaded lifecycle and proxy regressions). `mcp-startup-recovery-last.log` **2 passed,4 warnings** adds diverged lost-result/no replay/fresh-intent fence and denied peer mutation. UI/build last results below. Initial build failed only test literal-type inference; corrected typed fixtures, retained failed artifact. Extra old Skills review was confirmed already fixed in b8afc5c3; duplicate source/test edits removed. Its redundant isolated check log retained separately, not new feature proof.
- Remaining GB-043 code: intended per-tool policy inspection/edit UI and provider-specific account configuration must be qualified against existing owners; no invented provider auth RPC or claimed account connectivity. Comprehensive actual browser/native/provider acceptance remains deferred/restricted. Source build UNSERVED; voice/large avatars paused, popup/native visual gap and real unknown request remain unchanged.

- Final affected UI evidence: `mcp-startup-ui-last.log` **4 passed/3 files**; `mcp-startup-build-last.log` theme/TypeScript/Vite/no-mock **passed**, existing chunk advisory only. No served-build switch. Ruff affected/new files and diff whitespace passed.


### 2026-10-21 — GB-041 local prompt-template transfer source checkpoint

- Existing registry `configuration.export_template/import_template` owns exact owner-local schema/version/export policy/source-bot revision. Export copies only specialty/summary/operator instructions; no history, account metadata, tools, grants, plugin state or endpoints. Recognizable secret content refused rather than masked copy. This is not a guarantee arbitrary private prose can be automatically detected; explicit owner review remains. Source digest and fixed local filename validated by UI before a browser download request; actual OS save remains unconfirmed. Protected definitions and stale source revisions reject.
- Existing authenticated creation endpoint accepts validated `template_snapshot`, creates a NEW specialist with empty explicit allowed_tools and unverified source/version/hash provenance. No source identity/role/history mutation or tool grant. Authority/metadata fields refused; unsafe template rejected before creation; snapshot intents retain only a digest. Existing durable agent.create receipt handles repeated exact intent and unknown recovery; no separate template runtime/store/service. UI Specialist settings exports current SAVED revision while retaining local draft; New agent accepts local JSON snapshot and persists uncertain creation intent for original lookup only.
- Compatibility/rollback: additive ordinary registry metadata.template properties only, normal existing instance/registry creation and configuration_revision0; no migration. Preserve created records/operation receipts/device creation journal on rollback. No real user agents, conversations, metadata, memory, packages, external publishing or production changed.
- Evidence `~/.cache/jaeger/verification/blueprint-20261020/template-transfer-backend-final.log`: **102 passed/25 warnings**, local actual Gateway handler export plus two new owned fixture specialists, exact nonce dedupe, source unchanged/history retained, forbidden metadata, protected/stale/prefixed scope, recognizable secret refusal and existing registry/proxy regressions. `template-transfer-ui-last.log` **6 passed/3 files** (source/digest/private-field refusal, saved-revision export while draft retained, one local snapshot creation+uncertain journal, existing original lookup); `template-transfer-build-last.log` theme/TypeScript/Vite/no-mock **passed**, chunk advisory, **UNSERVED**. Last owner-only run after role-expression cleanup noted below.
- GB-041 remains code_remaining for saved custom-template catalog publication/version selection through existing registry metadata. A public publisher is unconfigured; no invented marketplace RPC. Broader actual browser/native/live acceptance deferred. Existing voice/large-avatar exclusions, popup/native gap and unknown request preserved.

- Final source follow-through: `template-transfer-owner-source-final.log` **9 passed/11 warnings**, including 3 new local export/import/unsafe-input fixtures and existing agent API cases after final source edits. Rejected snapshot intents persist only a body digest and a known rejection receipt, so private rejected text is not copied into the operation journal and the UI can reconcile the failure instead of becoming stuck behind a missing receipt. Source records/permissions/history remain unchanged. Ruff affected sources/new fixture and whitespace pass.
- Lightweight remaining-code checkpoint (same ledger, not completion): GB013 PDF;015 artifact→Library;016 sharing;026 host status/screen;029 clipboard/connection;032 connectors/grants controls;037 actual reusable workflow execution;039 webhooks;041 saved custom template catalog/version selection;043 tool-policy/account UI qualification;045 team access;046 onboarding;047 security status;048 native notification navigation;052 updates;059/069 provider-channel reconciliation;060 spending policy;065 browser access;066 machines;072 administration;075 distribution validation;076 email contracts;078 Messages grants. Ledger remains24 code_remaining/16 unreconciled/34 implemented_awaiting_acceptance/5 excluded. Unreconciled is not completed. External activation, production/native/browser/download acceptance remain separate restrictions; paused voice/large-avatar scope unchanged.
