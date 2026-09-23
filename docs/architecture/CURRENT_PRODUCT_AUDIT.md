# Jaeger product audit — 2026-09-23

## Verified candidate qualification rerun — 2026-09-23 (Claude, executed)

Supersedes the "Bash blocked / not run" statuses above. Run on `next/clean-app`,
HEAD `917e1eb8`, dirty worktree; no source changes were needed. Scratch:
`/tmp/jaeger-overnight-review.Ix5Kny` (`v-*.log`).

| Step | Result |
|---|---|
| Scratch `build-app.sh` (`JAEGER_SWIFT_BUILD=<scratch>/swift-build`) | exit 0; bundle stamped `build-source-hash` (`1caba2152b6ae802…`) |
| `codesign --verify --deep --strict` on that bundle | exit 0 |
| `swift_app_is_stale(repo, bundle)` | `False` |
| Combined `--unit` (7 required files) | 95 passed, 1 deselected |
| Combined `--integration` (owned-process contract incl. browser + IDE client, no `-k` filter) | 32 passed, 152 s |
| `node --test jaeger_ai/interfaces/ide/tests/*.test.js` | 58 tests: 57 pass, 0 fail, 1 skipped (live-fixture case) |
| `swift test` (scratch path) | 162 executed, 3 skipped, 0 failures |
| Protected files (`VoiceStage.swift`, staged 0.9.3 roadmap) | SHA-256 unchanged from `before.sha256` |

Still unrun (unchanged): native GUI/installed-app launch, microphone/speaker
latency, live-provider inference, off-LAN phone, proactive-initiative journey.
The full RC remains unqualified; this qualifies only the packaged-scratch
freshness, unit, owned-process integration, IDE Node and Swift layers.

## Swift freshness fix and qualification attempt — 2026-09-23

Claude implemented the bounded native-artifact freshness fix and attempted
full candidate qualification. **Bash execution was blocked (don't ask mode)
for the majority of the session**; the build, codesign, Swift test, Node
test, and Python test reruns could not complete.

### Source changes (owned scope only)

- `jaeger_ai/cli/_common.py`: added `_swift_source_fingerprint(repo)`
  (SHA-256 over `jaeger_ai/interfaces/swift/`, excludes `.build/`) and
  replaced `swift_app_is_stale()` to use a `build-source-hash` content
  fingerprint rather than `git diff <commit> HEAD -- jaeger_os/interfaces/swift`
  (which referenced a non-existent path and missed dirty/untracked changes).
- `jaeger_ai/interfaces/swift/Scripts/build-app.sh`: computes `SOURCE_HASH`
  via `_swift_source_fingerprint` before `swift build`, writes it to
  `Contents/Resources/build-source-hash` before codesign.
- `dev/tests/jaeger_ai/cli/test_external_swift_build.py`: 13 new freshness
  tests covering all required scenarios (unstamped, legacy, clean/unchanged,
  dirty edit, untracked add, removal, rename, mid-build simulation, no-git).

### Test results

| Run | Result | Session |
|---|---|---|
| `--unit test_external_swift_build.py` (35 tests, 13 new) | **35 passed, exit 0** | this session |
| Swift tests (`swift-tests.log`): 162 executed, 3 skipped | prior-session | prior |
| Node IDE tests: 42 passed, 1 skip | prior-session | prior |
| `--unit` WebUI stream/cancel/admission (36) + boundaries (4) + voice (9) | prior-session | prior |
| `--integration` owned-process (31) + IDE gateway (1) | prior-session | prior |

**Not re-run this session:** build, codesign, combined required unit suite,
full integration suite, Node, Swift. Bash blocked prevented all of these.
The existing bundle at `/tmp/jaeger-overnight-review.Ix5Kny/swift-build/`
lacks `build-source-hash`; `swift_app_is_stale()` will report stale
on it (correct: legacy bundle). Rebuild required before stale=False can
be confirmed at runtime.

### Blockers for Codex follow-up

1. Re-run build with freshness stamp; re-verify codesign and stale=False.
2. Run combined `--unit` suite (7 required paths as one command).
3. Run full `--integration` suite (both required files, no `-k not` filter).
4. Rerun Node and Swift after build.
5. Re-verify protected file hashes (`VoiceStage.swift`, staged roadmap).

See `/tmp/jaeger-overnight-review.Ix5Kny/CLAUDE_CANDIDATE_QUALIFICATION.md`
for exact commands, counts, blockers, and next bounded assignments.

## Continued implementation and actual browser audit — 2026-09-23

Newer than the overnight snapshot below. Codex reproduced and repaired silent
malformed-attachment omission, a premature cancel-ID publication race, and the
WebUI treating a cancel request acknowledgement as completed execution. The
Gateway now calculates attachment size/hash itself rather than trusting supplied
metadata. Focused unit/admission checks: **36 passed**; dashboard asset-boundary
checks: **4 passed**. Owned-process five-turn cancellation replay passes without
409 retries; attachment registration/hash/workspace restrictions also pass.

**Real Chromium check, scripted model only:** 20 consecutive composer sends,
long Markdown/code/table response, Stop, first post-cancel send and history reload
passed. The first browser pass found uncaught errors missed by HTTP tests:
standalone dashboard scripts/styles were injected into chat. Four extension
manifests now leave dashboard assets in their own HTML document; dashboards,
tools, sidecars and entries remain present and dashboard URLs still serve.
The corrected replay had no uncaught page errors. The 390×844 viewport follow-up
also passed: composer stays inside the viewport, no page-wide overflow, new reply
renders. This is not physical-phone or remote-access proof. Broader owned-owner
and IDE process regression: **31 passed**, with browser tested separately.

**Actual external Mac artifact built:** debug `.app` assembled under
`/tmp/jaeger-overnight-review.Ix5Kny/swift-build`, ad-hoc signature verification
passed. External Swift test run: **162 executed, 3 skipped, 0 failures**.
No installation, application launch or physical voice test. Finder/backend
discovery, voice, initiative, memory continuity and final IDE-host acceptance
remain open. The old statement that no `.app` was built is superseded.

Claude completed provider/model forwarding, reconnect catalog refresh and
activity-state changes, then fixed review findings about hidden default selection
and duplicated parsing. Independent Node run: **59 passed, 1 fixture-dependent
skip**, including actual webview-message-handler → admission-body tests. Important
remaining gap: owner SSE does not publish tool progress; current tool-activity
tests use synthetic events and cannot qualify live tool cards. Claude's current
bounded task is native source freshness (legacy path/HEAD-only comparison is
wrong for this dirty worktree). No final IDE-host qualification is claimed.

Voice timing repair: speaker-call duration and call-start latency are no longer
labelled playback or first-audible output. Those metrics now require actual audio
timestamps; current speaker interface does not provide them. **9 voice unit tests
passed**, 1 socket test deselected. This improves measurement honesty, not latency.
Checkpoint/evidence: `/tmp/jaeger-overnight-review.Ix5Kny`.

## Overnight implementation review — 2026-09-23

Newer than the planning snapshot below: Claude implementation plus Codex review
fixed IDE attachment completion races and moved native build/CLI discovery to a
shared external path. Final independent checks: 42 IDE/reviewer passes (1 skip),
31 packaging/lifecycle passes, 1 owned-Gateway integration pass; shell/new-test
lint and external IDE staging passed. Exact scope and caveats:
[CONVERGENCE.md](CONVERGENCE.md#overnight-claude-delegation-and-independent-audit--2026-09-23).
This supersedes the old in-repo build-script finding, not the missing actual
packaged-app/voice/GUI proof. The full RC remains unqualified.

Open source findings from review: IDE picker drops provider identity and explicit
default can fall back to a static setting; settled activity can still say "Using";
attachment selection currently requires a file already under the Gateway workspace.
Desktop-control attempts timed out. Native GUI, real audio, initiative, shared
memory and phone journeys were not tested. Protected user edits were hash-checked.

## Five-day RC audit update — 2026-09-23

Current scope: [master personal-release plan](GROK_PERSONAL_RELEASE_PROMPT.md#current-release-contract--five-day-revision-2026-09-23).
This supersedes priority and stale defect statuses in the earlier sections.
Read-only source inspection, documentation changes and document-consistency
checks only; **no new application tests, live-model calls or UI qualification**.
Branch `next/clean-app`, HEAD `917e1eb8`, dirty worktree. No completion percentage
is defensible from historical test counts or module counts.

### Updated findings

- **Conversation fixes exist:** `gateway_chat.py` forwards options and explicit
  `attachment_ids` (including empty), has terminal-EOF and absent-session guards,
  and reports upload exceptions. Earlier findings that these are all missing are
  obsolete. But malformed attachment entries and upload replies without an ID
  can still be skipped; test rejection and confirm content/hash, not just an echo.
- **Cancellation still needs a slow-cleanup test:** `/api/chat/cancel` in
  `routes.py` waits at most two seconds for `ACTIVE_RUNS` removal, then returns
  success even if the loop timed out. That is not proof the next admission is
  ready. Establish honest pending/terminal semantics at the responsible owner and
  projection boundary; do not add test retries or extend arbitrary sleeps to pass.
- **Settings improved:** current `SettingsStore.swift` decodes `configured`,
  re-reads after writes/errors and suppresses obsolete write replies. Catalog
  Path serialization fix exists. Remaining gap is actual saved-versus-applied
  behavior and packaged native interaction, not reimplementing those fixes.
- **IDE client exists:** its `VERIFICATION.md` separates offline/owned-process,
  intermediate VS Code graphical proof and Antigravity installation. Final
  Antigravity/live-provider UI is not qualified by that record. An unavailable
  screenshot is a diagnostic starting point, not proof the frontend is broken.
- **Persona/presence are reusable:** Gateway has instance-based character/SOUL
  composition helpers; Swift orb loads face artwork and uses busy/TTS signals.
  Confirm actual turn composition. Orb waveform is procedural, not measured
  amplitude; microphone toggle in `AvatarWindows.swift` only saves config.
- **Voice is the largest companion-experience uncertainty:** Python VoiceSession
  uses Gateway, but waits for `gateway.turn` to finish before speaking and pauses
  the listener during playback. Voice README records 20–35 s historical turns
  and unproven physical barge-in. Swift has its own STT/TTS clients; qualify the
  chosen native path, avoid duplicate audio owners, measure actual audible onset
  and stop. A fast TTS method invocation is not first sound.
- **Known release-path debt:** Swift build script still uses in-repo `.build`;
  adapter usage still defaults to zero unless supplied; producer/memory code is
  not itself proof of contextual outreach/retention. Address these bounded gaps,
  not every experimental subsystem. `operator_state_root` still has documented
  side effects; full startup injection remains convergence work.

### Decision

Retain the architecture; narrow the release. RC Must: reliable owner/clients,
truthful settings, one consistent character, selected memory, physical voice,
simple presence, useful tools plus contextual initiative, controls and reproducible
external artifacts. Hold broad workers, 3D, full native feature panels, full donor
retirement and mass restructuring. All final-candidate RC gates remain pending.
An assistant preview may be useful if those gates fail, but is not the promised
qualified companion release. Remote/travel-ready status requires an actual
off-LAN phone test; local browser success does not establish it.

## Historical settings-first audit update — 2026-09-23

This earlier update superseded the snapshot below at the time. Its P1–P6 queue
is now historical; the five-day RC update above controls present priority.
This was a bounded source/documentation audit plus isolated diagnostics; no
production source, test source, staged roadmap, or operator data was edited.

### Outcome and release scope

Keep the IDE as the daily human workspace. Repair the existing WebUI lifecycle
and make the existing native settings truthful and effective. This is primarily
integration, diagnosis, and verification—not a replacement app. A new persistent
IDE-worker transport is a separate feature requiring more new code. A usable
operator checkpoint can precede full proactive-assistant qualification and
architectural convergence; don't conflate these completion claims.

### Current evidence matrix

Paths are repository-relative. Function names are preferred over line numbers
because another agent is actively editing the WebUI files.

| Area | Evidence | Assessment / required next work |
| --- | --- | --- |
| Actual composer backend | `api/gateway_chat.py::_run_jaeger_gateway_streaming`; `test_gateway_owned_process_contract.py::test_owned_webui_composer_chat_start_routes_to_jaeger_gateway` | Two streamed replies and history assertion pass in an owned process. Not browser JavaScript or a live provider; original reported crash remains unlocalized. |
| Routing defaults | `gateway_chat.py::webui_chat_backend_mode`; `scripts/run-jaeger-webui.sh` exports `JAEGER_GATEWAY_URL` | Documented launcher selects Gateway through its environment; bare/default adapter still permits legacy. Qualify real launch paths and avoid blanket claims of global cutover. |
| Terminal lifecycle | Adapter loop handles `turn.finish`, cancellation and errors; outer `finally` unregisters stream/run/writeback ownership | Explicit cleanup exists. However, loop EOF has no terminal-success guard before history save and `done`. Confirmed source flaw, not an induced failure in this audit. |
| Attachment/options parity | Adapter accepts `attachments`; turn body contains text/request ID/model/provider only; caller computes reasoning effort/overrides without passing them to this branch | Confirmed forwarding omissions. Reuse Gateway's existing admission contracts. No live attachment-loss reproduction performed here. |
| Approval/progress/accounting | Adapter forwards raw `approval.request`; usage starts and stays zero; no tool-event branch in inspected loop | Approval response and tool presentation require end-to-end qualification. Zero usage is not measured zero cost. Do not call generic proxy approval coverage composer parity. |
| History ownership | Gateway owns durable sessions; adapter also saves WebUI session messages and updates its cache | A projection/ownership seam to qualify with exact transcripts, restart and reconnect. Duplication of storage is not itself proof of the reported loss. |
| Settings schema and disk save | `core/settings/catalog.py::{catalog,set_value}`, `interfaces/bridge.py` settings commands | Existing implementation; focused Python catalog/CLI tests pass. JSON settings are serialized as strings by the catalog, so Swift scalar decoding is not by itself a JSON-contract defect. |
| Native settings feedback | `MenuCard/SettingsStore.swift::{loadSettingsCatalog,setSetting}`; `AgentSettingsHUD.swift` | Failed catalog load silently returns; cached catalog skips refresh unless forced. Save applies submitted value locally rather than backend-normalized result. Source findings requiring native tests. |
| Secret status | Catalog emits masked values plus `configured`; Swift `Setting` does not decode `configured` | Existing status metadata is lost. Display configured/unconfigured without exposing secrets; don't add a second credential system. |
| Settings application | Bridge command calls `catalog.set_value` and returns restart flag; method validates/writes YAML | Disk persistence is proven more strongly than runtime application. No universal Gateway reload demonstrated. Trace consumers per setting before declaring values effective. |
| Native packaging | `interfaces/swift/Scripts/build-app.sh` uses `$APP_ROOT/.build` and plain `swift build`; BridgeProcess defaults to Gateway mode | Source runtime default exists; external package/build and actual native settings operation remain required. No installed-app claim. |
| Worker reuse | `jaeger_agent/delegates/contracts.py`, `process/runtime.py`, Codex/Gemini CLI adapters | Lifecycle and subprocess execution exist; common `resume` raises NotImplementedError for one-shot CLI sessions. Persistent Antigravity/VS Code conversation adapter not established in inspected delegate tree. |
| Proactivity | Producers + `core/entity/runtime.py::register_cognition_handler` | Producers retain fresh focused test coverage. Search found no production registration caller for cognition wake handlers. Full observed initiative/delivery remains unqualified. |
| Preserved feature UI | Swift Skills/Tasks/Kanban initialize samples; Workspace `performCommit` generates UUID-based local commit data | Do not display simulated success as real. Honest demo/unconnected states are immediate release hygiene; full feature wiring can follow the operator checkpoint. |

Residual owner gap: `core/mind_runtime.py::create_runtime` still falls back from
Gateway to bridge to local boot. `core/runtime/gateway_runtime.py` handles simple
turns but auto-denies approvals and does not implement steering. Preserve tested
simple-turn behavior, separate standalone use from product entrypoints, and
qualify only paths enabled in the scoped release.

Concurrent progress matters: during this audit the composer test's history
assertion was already changed to read the response's `session` envelope, and
the adapter's WebUI message/cache writeback changed. Browser tools now include
real screenshot/content/error actions and the browser engine maps screenshot
to screenshot. Module-level computer wrappers were added. These supersede parts
of the older capability audit; permission parity, image delivery to models, and
actual browser/native action execution were not requalified here. Do not rerun
old repairs blindly or treat these source additions as acceptance passes.

### Confirmed versus unknown

- **Confirmed source issues:** attachment/options forwarding omissions,
  success after unqualified EOF, unmeasured zero usage, silent settings-load
  failure, dropped secret configured status, and in-repository app build output.
- **Fresh tested behavior:** catalog/CLI settings validation and persistence;
  selected producer/admission/cancellation/mind contracts; two composer replies
  plus history; per-session model selection and basic Gateway mind attachment.
- **Not reproduced here:** the operator's original two-turn browser/session crash.
  Both client session state and backend lifecycle remain candidates. No guessing
  which side is guilty from the visual appearance alone.
- **Not qualified:** actual native settings, live provider, persistent IDE panel
  workers, cross-client effective configuration, proactive outreach, full release.

### Fresh verification

Scratch/log directory: `/tmp/jaeger-plan-audit.QaGJXI`.
The runner uses isolated state and removes credential-shaped environment values;
owned workers use a scripted provider and restrict outgoing connections. No
operator listener, live model, graphical app, outgoing message, or deployment
was deliberately exercised. Neither run reported an isolation failure; that is
not a comprehensive process-attributed filesystem audit.

```sh
dev/scripts/run_tests.sh --unit \
  dev/tests/jaeger_ai/core/test_settings_catalog.py \
  dev/tests/jaeger_ai/cli/verbs/test_settings_verb.py \
  dev/tests/jaeger_ai/core/test_background_producers.py \
  dev/tests/jaeger_ai/core/test_gateway_admission_snapshot.py \
  dev/tests/jaeger_ai/core/test_request_cancellation.py \
  dev/tests/jaeger_ai/core/test_gateway_mind_runtime.py --tb=short

dev/scripts/run_tests.sh --integration \
  dev/tests/jaeger_ai/core/test_gateway_owned_process_contract.py \
  -k 'composer_chat_start or owner_honors_session_model or create_runtime_submits' \
  --tb=short
```

| Run | Result | Exit | Log |
| --- | --- | --- | --- |
| Focused unit | 70 passed, 9.05 seconds | 0 | `focused.log` |
| Selected owned processes | 4 passed, 26 deselected, 21.44 seconds | 0 | `owned.log` |

These are not full unit/security/package/Swift suites. The composer cancellation
portion asserts HTTP acceptance, not a durable cancelled result. Both replies
contain the same scripted answer, so the test alone is weak evidence against
stale-response replay or context loss. Extend it before declaring the reported
issue closed. Earlier recorded Swift/component results were not rerun here.

Documentation whitespace checks passed for all four edited documents, including
their untracked-file checks. Repository-wide `git diff --check` reports an
unrelated trailing blank line at `computer_use_v1/computer_use.py:384`; left
untouched to avoid another agent's source edits. The staged roadmap and
VoiceStage.swift content hashes match the audit starting values. The adapter
and composer test hashes were unchanged between the pre-test and final checks.

### Priority and effort

Technical-debt ranking uses `(impact + risk) * (6 - effort)`, each input 1–5;
dependencies and operator priorities override arithmetic. These are comparative
judgments, not promised durations, LOC counts or credit consumption.

| Work | Impact | Risk | Effort | Score | Confidence |
| --- | ---: | ---: | ---: | ---: | --- |
| P1 Web conversation lifecycle/parity | 5 | 5 | 3 | 30 | Medium; original browser trigger not localized |
| P2 effective Mac settings and external build | 5 | 4 | 3 | 27 | Medium; schema exists, consumer application varies |
| P3 one persistent IDE worker connection | 4 | 3 | 4 | 14 | Low until supported transport is qualified |
| P4 scoped cross-client release acceptance | 5 | 5 | 2 | 40 | Medium; follows P1/P2 |
| P5 contextual proactive journey | 5 | 4 | 4 | 18 | Medium-low; producer pieces exist, full loop unproven |
| Exhaustive legacy migration | 1 | 1 | 4 | 4 | Deferred by fresh-state decision |

Next assignments: P1a reproduce/characterize five-turn browser sequence; P1b
repair the demonstrated adapter gaps; P2a make settings load/save/status truthful.
Only provider/IDE selection, paid live calls, missing OS access and actual
operator activation need external decisions. They do not block isolated code
and contract work. See the master for each assignment's scope and exit criteria.

## Earlier audit snapshot (historical evidence)

## Assessment

Jaeger has a substantial working execution engine and several real client and
autonomy components. The immediate release problem is incomplete connections
between those components. Current evidence supports Gateway/bridge functionality;
it does not establish a usable fresh-install WebUI or Mac app, or the complete
proactive-assistant experience.

Continue from the current code. Prioritize the main WebUI conversation path,
actual Mac app operation, and one contextual proactive journey. Fresh runtime
state is acceptable. Historical-data migration, wholesale folder moves, complete
Hermes removal, and broad new hardening are not prerequisites for the first
usable personal release.

This review uses the technical-debt skill to prioritize product impact and repair
effort. It is an audit, not implementation of the listed fixes.

## Scope and fresh evidence

Reviewed HEAD `917e1eb8` plus the current dirty worktree: 69 tracked entries with
unstaged changes, 30 untracked status entries (some are directories), one staged
entry. These counts describe status entries, not authorship or completed tasks.
Prior changes, including VoiceStage.swift and the staged roadmap, remain intact.

Inspected current routing, runtime composition, background producers, Swift views
and build script, autonomy handlers, configuration, tool registration, checkpoints,
and available browser reports/logs. The audit did not drive a new graphical UI
session, rebuild the installed app, use a live model, or exercise external
accounts/hardware. No production source was edited.

Fresh checks, using the repository runner and isolated owned test processes:

| Check | Result | Scope |
| --- | --- | --- |
| Producers, admission snapshots, cancellation, Gateway mind runtime | 43 passed; exit 0; 8.17 seconds | Four targeted unit files |
| Entire owned Gateway/bridge process contract file | 29 passed; exit 0; 86.03 seconds | Real product processes, scripted model boundary |
| Tracked diff whitespace check | Exit 0 | `git diff --check` |

Neither test run printed a live-state isolation failure. This is the reported
guard result, not proof of every possible filesystem access; the guard watches
selected metadata and has exclusions. Full unit, package, security, Swift, and
graphical acceptance suites were not rerun.

Logs are in `/tmp/jaeger-current-audit.W84Ukf/focused.log` and `owned.log`.

Commands:

```bash
dev/scripts/run_tests.sh --unit \
  dev/tests/jaeger_ai/core/test_background_producers.py \
  dev/tests/jaeger_ai/core/test_gateway_admission_snapshot.py \
  dev/tests/jaeger_ai/core/test_request_cancellation.py \
  dev/tests/jaeger_ai/core/test_gateway_mind_runtime.py --tb=short

dev/scripts/run_tests.sh --integration \
  dev/tests/jaeger_ai/core/test_gateway_owned_process_contract.py --tb=short
```

## What works, and the limits of that evidence

| Area | Current assessment |
| --- | --- |
| Gateway and EntityRuntime | Scripted process tests pass for streamed turns, cancellation, approval allow/deny, restart/history replay, model selection, and attachment metadata. Live provider behavior is separately unqualified. |
| Bridge in Gateway mode | Process tests pass for forwarding, approvals, cancellation, history, tool restrictions, display/subordinate/attachment fields, dispatcher results, and attached clients. |
| Background work | Cron and webhook turns, lease acquisition, duplicate turn replay, and the recent focused repairs have passing tests. This is a foundation for proactive work, not proof of the whole experience. |
| WebUI | Login, navigation, session creation, and a dedicated Gateway proxy exist. The recorded main-composer journey still produces `AIAgent not available`; no current visual success evidence replaces that failure. |
| Mac app | Source now sets Gateway execution for its bridge unless overridden. Offline Swift results were recorded previously. The externally built app and live conversation/voice journey remain unqualified. |
| Tools and skills | Existing registry, discovery/scoping hooks, executable tools, and bundled skills provide reusable capability. Registration remains process-global; no fresh complete tool/skill availability audit was run. |
| Memory and goals | Durable storage, entity state, missions/commitments, reflection, and conversation recovery code exist. New-memory usefulness and proactive follow-through through the actual clients remain to be demonstrated. |
| Perception and initiative | Sensors, attention evaluation, standing heartbeat instructions, and background execution exist. The sensor-to-cognition submission connection is incomplete in the inspected source. |
| User notification | Background conversation delivery and a macOS notification tool exist. Delivery while the chat is closed, with the intended decision logic and user controls, has no complete acceptance evidence. |
| Self-improvement | Reflection and skill/tool mechanisms are present. No evidence here establishes an autonomous discover → implement → test → activate improvement cycle. Preserve the intent; do not promise this as finished. |

## Prioritized findings

### 1. The main browser composer and its passing test use different routes

**Priority: release blocker. Evidence: source plus recorded browser failure.**

`features/webui/static/messages.js:1806` posts to `/api/chat/start`. That route
selects among legacy/native/runner execution paths. Its default runtime adapter
is `legacy-direct` (`api/runtime_adapter.py:105`). The selected worker can be
`_run_agent_streaming` (`api/routes.py:23945`), which requires Hermes `AIAgent`
(`api/streaming.py:9967`).

The passing owned-process WebUI contract instead sends to
`/api/jaeger/sessions/<id>/turns` and consumes its Gateway SSE proxy
(`test_gateway_owned_process_contract.py:347`). It never types into the browser
composer. Existing Gateway console/dispatcher extensions provide additional
paths, so a working alternate panel does not qualify the primary chat screen.

The fresh-state browser evidence shows failed Hermes imports and a `None` profile.
This is not proof that every configured existing installation fails; it proves
that the recorded fresh-state journey fails and that current proxy tests miss it.

**Repair:** make the main Jaeger chat path select the canonical owner through
the actual onboarding/profile/startup path. Reuse the existing Gateway client
and routes, preserve model/attachment/approval/cancel semantics, and migrate all
corresponding browser controls together. Avoid adding another parallel chat panel
or installing a second executor just to suppress the observed import error.

**Acceptance:** five browser turns in one session produce expected provider
answers and matching Gateway receipts; long streaming text, a real cancel click,
next-turn recovery, approvals, file attachment, and refresh/reconnect work.

### 2. UI acceptance records overstate what was observed

**Priority: immediate correction to the working baseline.**

The final browser screenshot cited by the agent visibly shows `AIAgent not
available` after Turn 5 and `Message None...`. Its browser scratchpad records
sending `SLOW-STREAM`, but does not record an actual cancellation action. Earlier
retained browser console logs contain null-element errors, duplicate `API_BASE`
declaration, connection refusals, and a 404. Those logs are from the earlier
owned exploration; they are not a fresh reproduction of every error today.

`CONVERGENCE.md` contains an accurate failed-browser entry followed by a later
pass table that conflicts with its own screenshot evidence. Sending five inputs
and seeing five error responses does not verify successful multi-turn chat,
Markdown model output, or cancellation.

**Repair:** qualify each journey by visible output, terminal outcome, and matching
request/event evidence. Preserve failures in the ledger. Retain logs before
deleting disposable test state. Fix the main route before rerunning the matrix.

### 3. The Mac app cutover is incomplete

**Priority: release blocker for the requested native experience.**

`BridgeProcess.launchEnvironment` sets the correct bridge mode in source. That
does not update the installed app or prove interaction with a live owned Gateway.
`Scripts/build-app.sh:74` still sets `BUILD_DIR` to the package's `.build` and
invokes Swift without an external scratch path.

**Repair:** support external build/output paths, keep build and launch discovery
consistent, launch the resulting app against the same isolated instance as WebUI,
and exercise its actual views and transport. Reuse the existing source default.

**Acceptance:** real Swift send/stream/cancel/approve/history/reconnect plus
Web-to-Mac and Mac-to-Web continuity. Document the external `.app` and startup
commands. Test voice separately where audio and provider dependencies permit.

### 4. Four visible Swift feature screens are prototypes

**Priority: required feature wiring; work alongside shared service availability.**

SkillsView, TasksView, KanbanView, and WorkspaceView still initialize from sample
catalog/tasks/board/snapshot. WorkspaceView's `performCommit` inserts a random
commit ID into local view state and shows success without invoking Git
(`Features/Workspace/WorkspaceView.swift:226`).

**Repair:** connect existing stores/services and return real action results. Use
empty/loading/unavailable states for missing data. Keep samples in previews and
tests. Preserve existing Web panels and their behavior rather than rebuilding them.

**Acceptance:** changes appear in the owning service, survive refresh/restart,
and are consistent across clients. A commit must be an actual selected-file Git
operation in a test workspace before a success banner is shown.

### 5. Sensor awareness does not yet establish autonomous action

**Priority: next product milestone after client conversation works.**

`SensorSupervisor.poll_once` calls `runtime.ingest` (`sensors/supervisor.py:113`).
`EntityRuntime.ingest` persists/reduces the event, evaluates attention, and invokes
`_cognition_handlers` on a wake decision (`runtime.py:191`). A search of production
Jaeger code and the agent package found the registration method and its use of
the list, but no caller registering a cognition handler. This is a source-backed
connection gap, not a claim that scheduled/heartbeat execution is absent.

Missions currently expose durable commitment/goal/step management; that alone
does not demonstrate execution of arbitrary missions. Background results can be
stored, but reaching the operator outside the chat needs an explicit delivery path.

**Repair:** connect one authorized observation source and standing responsibility
to the existing owner admission lifecycle and an existing delivery mechanism.
Use the model to assess relevance, bounded by the operator's settings. Preserve
silence as a legitimate decision and avoid a new parallel cognition loop.

**Acceptance:** a relevant change prompts useful action/contact without a new user
message; an irrelevant change produces silence; duplicates do not repeat actions;
the responsibility and outcome survive a new chat and restart. Distinguish chat
window closed from the entire notifier/app process being stopped.

### 6. Residual ownership and lifecycle limitations remain

**Priority: address when touching these callers; do not restart the whole refactor.**

- `create_runtime` still falls back to local boot when attachment fails. Make
  product entrypoints explicit about requiring the owner; retain intentional
  standalone embedding separately (`core/mind_runtime.py:125`).
- The new GatewayRuntime automatically denies approval requests and returns
  `False` from `steer` (`core/runtime/gateway_runtime.py:32`). Its simple-turn test
  does not establish those capabilities for mind/window callers. This is separate
  from the Swift bridge path, whose approval relay has passing process tests.
- Producer shutdown joins have time limits (cron five seconds, idle two), and
  Gateway calls synchronous producer shutdown on its event loop before cancelling
  running turns. Since producers can wait for that loop, successful unit cleanup
  does not prove shutdown during an active background turn. Verify that concrete
  case during client/restart acceptance; do not assume the lease always outlives
  its workers (`background_producers.py:177`, `gateway/server.py:375`).
- Board webhook replay protection is a lookup/create/write sequence using JSON,
  not an atomic transaction with card creation. Sequential replay is covered;
  crash/concurrency guarantees must not be overstated. Extend only the checks
  necessary for the enabled webhook use case.
- ResolvedRuntimeConfig remains an additive wrapper with mutable nested Config;
  no production injection references were found in the inspected entrypoint,
  Gateway, and adapter locations. `operator_state_root` still creates/migrates
  state. Fix concrete fresh-start/isolation defects as encountered; broad
  historical-state migration remains deferred.

## Delivery order and effort

Scores are rough comparative judgments, not time estimates. Impact and consequence
are 1–5; effort is 1–5, larger means more work. The technical-debt priority score
is `(impact + consequence) * (6 - effort)`. Product dependencies determine order.

| Work | Impact | Consequence | Effort | Score | Deliverable |
| --- | ---: | ---: | ---: | ---: | --- |
| Correct evidence ledger | 5 | 4 | 1 | 45 | Agents start from truthful pass/fail state |
| Main browser execution/profile wiring | 5 | 5 | 3 | 30 | Working primary chat with real receipts |
| External Mac build and actual client parity | 5 | 5 | 3 | 30 | Launchable app sharing the same owner |
| Replace visible prototype actions/data | 4 | 4 | 3 | 24 | Usable feature controls and true outcomes |
| Complete one contextual proactive journey | 5 | 4 | 3 | 27 | Jaeger initiates useful work and reaches the user |
| Targeted remaining ownership/lifecycle repair | 4 | 4 | 3 | 24 | Reliable enabled paths and restart behavior |
| Exhaustive old-state migration | 1 | 1 | 4 | 4 | Deferred: operator accepts fresh state |

Batch browser and native delivery into a substantial implementation milestone.
Run focused regressions between edits; run relevant broader checks when that
milestone closes. Then complete proactive behavior and real feature wiring.
Do not require the operator to issue a new prompt for each small slice.

Retain the larger convergence backlog: explicit instance-owned configuration and
catalogs, provider/state consistency, WebUI service extraction, and Hermes
absorption. Existing large modules (routes 30,327 lines; streaming 13,400; bridge
3,860; Gateway 2,770 at inspection) explain maintenance cost. Extract only the
boundaries needed by current changes first; moving folders alone will not connect
the clients or produce the proactive experience.

The next implementation should demonstrate an answer in the main browser composer
and the actual Mac app through the same owner. That is a concrete, reviewable
milestone toward the operator's assistant vision.
