# Assistant-core UI audit, 2026-11-08

Scope: cloud-only branch `fix/assistant-core-acceptance-20261108`, starting at
`ff71bb769bc56e4c6d7be6d540a86be73e291e07`. No Mac runtime, deployment,
real accounts, external messages, purchases, or provider-backed generation.

Latest scoped qualification: [reconciliation ownership and outcomes](assistant-core-reconciliation-20261108.md)
records 910 component tests in 201 files and a newly fingerprinted no-mock build.
The earlier measurements below retain their historical scope; every tab remains
PARTIAL and browser/phone/native acceptance is not inferred from them.

## Evidence levels

Source inventory is not end-to-end acceptance. Component tests substitute API
objects; browser contract tests use an isolated Gateway/SQLite/WebUI and a scripted
model boundary. Neither proves real-provider, microphone, camera, native Mac,
external connector, robotics, or remote-account operation.

## Acceptance status key

- **PASS**: a specifically named component/build check passed; not blanket product acceptance.
- **PARTIAL**: source/control wiring inventoried; component evidence is scoped to named tests, and end-to-end destination acceptance is incomplete.
- **BLOCKED**: the named test boundary could not execute. Browser visual/phone acceptance and installed native-host operations are blocked in this executor.

Every destination below is **PARTIAL** overall. No tab is marked fully accepted
from mocks or source inspection. Production build and named component suites are
**PASS** as separately recorded; Chromium execution is **BLOCKED**.

## Production navigation and backend ownership

`src/main.tsx` mounts `FirstRunGate > StableDemo`. `AppWindow` is embedded only for
workspace destinations. The other shell's tests alone do not prove the actual entrypoint.

| Visible destination / controls | Status | Implementation and backend connection | Audit limitations |
| --- | --- | --- | --- |
| Chat: start, send, stop, restore, rename, archive, delete, approvals | PARTIAL | StableDemo, ChatPane/WebHost; JaegerSource/Gateway session, send/stream, approval and task APIs | Pins/sidebar width are device-local; fork and schedule menu items are disabled. Link sharing does not grant access to another user. |
| Imagine: generate, import, tags, delete, board, send to chat | PARTIAL | StudioPage; `/v1/studio/providers`, `/generate`, `/assets`, `/board`; source.agentHome/uploadAttachment/send | Generation requires configured provider. No generation or provider credentials exercised here. |
| Library: media, documents, outputs | PARTIAL | CompanionPage; StudioPage media, source.library, source.taskArtifacts | Unsupported source capabilities show unavailable state. File ingestion/export needs separate content-level acceptance. |
| Automations: create/edit/pause/run history | PARTIAL | AutomationsPanel; source.schedules and revision-aware mutations | No real scheduled external effects exercised. |
| Feed: notifications/read state | PARTIAL | CompanionPage Feed; source.notifications | Transport/UI wiring, not proof of proactive reasoning. |
| Agents: roster, create, archive, rename, memory, knowledge, instructions | PARTIAL | AgentsRoster and source.agentActions/specialistControls/agentMemory/agentKnowledge | Agent links now resolve source.agentHome and select its durable session; failures block old-chat fallback. Provider-backed specialist execution remains unverified. |
| Agents / Characters | PARTIAL | CharactersPage; createAgent and specialist controls | Character creation is a real mutation, not a new independent product identity. |
| Agents / Memory & Skills | PARTIAL | KnowledgePage; source.skills/skillDetail/agentMemory/library | Later [request-ownership repair](knowledge-request-ownership-20261108.md) adds explicit detail errors/retries and stale-context guards. |
| More / Work / Pipeline | PARTIAL | HomeDashboard + PipelinePage; source.tasks and `/v1/pipeline` | Pipeline metadata is distinct from execution state. Failed refresh no longer reports a stale/zero summary; partial task/pipeline failures are retryable. |
| Work / Backlog | PARTIAL | BacklogPage; `/v1/backlog` list/add/update/assign plus event feed | Own records, not interchangeable with Gateway tasks. |
| Work / Tasks | PARTIAL | TasksWorkspace/TasksBoard; source.tasks/taskActions/agentHome/delegation/taskArtifacts | Proposal, approval, edit, cancel and lookup have dedicated component tests. No real side effects exercised by UI audit. |
| Work / Production | PARTIAL | ProductionPage and pipeline attachments/artifacts | Artifact read failures now show explicit retryable errors; stale task responses cannot overwrite the selected task. |
| Work / Calendar | PARTIAL | CalendarPage; source.schedules and tasks with ETA | Task and scheduler failures are now independently visible/retryable; due dates still load without scheduler support. |
| Work / YouTube | PARTIAL | YouTubePage and YouTube HTTP API | No publishing, downloads, credentials or real account effects exercised. |
| More / Research / Research | PARTIAL | ResearchPage; task proposals/approve/cancel, agentHome, artifacts | Proposal response is not verified research completion. |
| Research / Documents | PARTIAL | DocumentsPage; `/v1/documents` CRUD and `/ai-edit`, model inventory | Later [document repairs](assistant-core-followup-20261108.md) add serialized backend CAS and same-tab draft recovery. Real provider/browser editing remains unverified. |
| Research / Workspace | PARTIAL | WorkspaceBrowser; source workspace and Git controls | No operator repository mutation exercised here. |
| More / Machine | PARTIAL | MachineControlPanel; source.computers/policySources plus native broker | Native permission/system controls are unavailable in cloud browser. Do not infer installed-host health. |
| Settings gear | PARTIAL | Now opens `/settings/appearance`, the existing SettingsDialog implementation | Removed production access to the draft-only settings navigation. No new controls or fake saves introduced. |
| Existing `/settings/*` | PARTIAL | AppWindow → App → SettingsDialog registry; source-backed settings and WebUI integrations | Before this fix, StableDemo treated settings as chat and never mounted these controls. |

## Confirmed entrypoint defects selected for repair

1. Settings direct links display Chat instead of the existing settings implementation.
2. Conversation links copy the current page URL without session identity; opening on another browser can show a different conversation.
3. Compact navigation remains over the chosen destination until manually dismissed.
4. Development mock navigation loses its safety selector when the target has query parameters. A reload can unexpectedly use the live adapter. Production ignores mock flags; tests must preserve explicit `mock=0` overrides.

## Baseline

- `npm ci --cache /tmp/jaeger-npm-cache`: passed, 305 packages installed.
- `npm run build`: passed theme checks, TypeScript, Vite production build and no-mock check. Existing warning: chunks over 500 kB.
- Baseline component suite: 193 files, 807 tests passed (147.59 seconds). Existing React act/key warnings were non-fatal.
- Final integrated result is recorded below.

## Repair details

- Production gear and `/settings/*` use existing settings, embedded without a second navigation shell. Chat remains mounted behind settings.
- Session selection writes a real `?session=` URL. Copy/share/open-window use that session URL even from a workspace tab; these are authenticated app links, not public sharing grants.
- Explicit session links win over device preferences and most-recent-session heuristics. Missing linked sessions show an error rather than silently displaying an unrelated conversation. Back/forward changes the selected session.
- `/chat?agent=` resolves the requested agent's durable home, records the session in the URL, and shows errors without leaving the previous chat writable.
- Compact navigation dismisses on destination selection and route changes; desktop navigation stays open.
- Development mock selection survives destination queries/fragments and honors explicit overrides. Production no-mock validation remains required.
- Playwright supports an explicit test Python and system Chromium, and writes artifacts/reports outside source. Vitest reports/coverage also default outside source.

## Follow-up gaps and later repairs (not full acceptance)

- Workspace pages mount only while selected. The later [document-draft repair](document-draft-recovery-20261108.md) adds same-tab recovery with regression evidence; it does not claim permanent unsaved drafts or browser acceptance. Chat draft persistence has a dedicated browser contract.
- The later [historic-session repair](historic-session-navigation-20261108.md) fixes roster rows opening agent home instead of the selected historic session, with production-shell component evidence.
- Later [authority/streaming](assistant-core-authority-streaming-20261108.md),
  [durable outcome/recovery](assistant-core-outcome-recovery-20261108.md), and
  [foreground truth](assistant-core-foreground-truth-20261108.md) repairs strengthen
  Chat/Work state and execution evidence. The subsequent
  [foreground continuation](assistant-core-foreground-continuation-20261108.md)
  repair adds versioned, fully specified new-card transfer to the existing durable
  owner. Unresolved defaults, historical work and unsupported inputs do not silently
  resume. Overall stays PARTIAL.
- The [request-session ownership repair](assistant-core-request-identity-20261108.md)
  prevents cross-chat receipt replay and destination mutation, including legacy
  receipts. Its synthetic HTTP profile and cold skill-startup exclusions are explicit.
- The later [default Chat admission repair](assistant-core-default-admission-20261108.md)
  snapshots supported server defaults for ordinary new Chat while retaining
  instance workspace semantics, authority and drift rejection. Unresolved routes,
  historic work and queued default admission are not accepted by inference.
- The [queued Chat repair](assistant-core-queue-defaults-20261108.md) extends
  immutable defaults to Queue next, preserving replay, promotion and instance
  paths. Confirmed-reconciliation queue continuity remains a separate follow-up.
- The [reconciliation repair](assistant-core-reconciliation-20261108.md) preserves
  failed/cancelled terminal state and streamed partial text instead of suppressing
  failure. It also protects newer session ownership and eligible queue progression.
  Real native-bridge restart remains unqualified. Later [combined qualification](assistant-core-combined-qualification-20261108.md) covers bounded resident request seals, stable lead identity, selected-agent handling and specialist scope, without claiming browser or external-account acceptance.
- Source-backed capability presence does not prove native-host availability, real provider credentials, external connector authorization, output quality, or a completed autonomous workflow.

### Parallel workspace error-state repair

Calendar and Pipeline/Production were repaired by the workspace-error task in the
same checkout. Failed reads no longer become empty success states. Calendar
supports due dates without a scheduler and excludes succeeded tasks. Production
has retryable artifact failures and stale-response guards. TaskBanner distinguishes
independent task/pipeline failures, labels last-known linkage, blocks unavailable
record mutations, and reloads authoritative linkage after attach. The worker
reported 16 focused component tests passing after independent review; these are synthetic API tests, not
live service acceptance.

## Browser execution boundary

Production browser contract was attempted using the isolated fixture and
`JAEGER_TEST_CHROMIUM=/usr/bin/chromium`, with Python 3.12 in the external test
venv and workspace packages on `PYTHONPATH`. The Gateway/WebUI fixture started
and its external production build passed. Chromium could not create a context:
`chrome/browser/process_singleton_posix.cc:297 socket() failed: Operation not
permitted (1)`. An authorized escalated retry had the same restriction and was
stopped after three infrastructure failures; 18 scenarios did not run. No browser
scenario passed and no screenshots/phone visual acceptance are claimed.

The initial browser download attempt returned a 0 MiB invalid ZIP from the
official Playwright CDN. Using installed Chromium avoided that download issue,
but not the runtime socket restriction. Further identical retries were stopped.

For an executor that permits Chromium's local sockets, the committed test config
accepts `JAEGER_TEST_PYTHON`, `JAEGER_TEST_CHROMIUM`, and
`JAEGER_UI_TEST_OUTPUT`. Use an isolated state/home and the repository package
paths, and run `npx playwright test --project=chromium --workers=1`.

New browser regressions cover session links overriding device selection and
surviving reload, existing appearance settings, and automatic compact-navigation
dismissal. They remain unexecuted because of the browser startup boundary.

### Independent review follow-up

- Restoring Chat at `/` now replaces that history entry with the selected session
  URL before another conversation is pushed. Back can recover the original chat.
- Embedded Settings/workspace pages render the existing command palette; Cmd/Ctrl+K
  is no longer an invisible shortcut.
- Deleted linked conversations show “Conversation unavailable” with an explicit
  “Open recent conversations” recovery action. They do not promise reconnection or
  silently switch the recipient of a conversation.
- Full intermediate component rerun: 194 files, 823 tests passed. This count is not
  claimed as validation of later review edits.
- Final focused review regression suite: 4 files, 72 tests passed (13.41 seconds),
  including actual Settings components, restored-session Back, agent/session deep
  links, unavailable-session recovery, command palette, and mock-flag navigation.
  React act warnings remain non-fatal. Final integrated build and aggregate checks
  are owned by the parent task after all workers finish.

Workspace review also verified stage-only TaskBanner navigation reloads details and
context-generation guards prevent late attachment/stage completion from changing
or navigating a newly selected task (three additional regressions).

## Final integrated component result

**PASS**: `npm test -- --maxWorkers=2 --reporter=dot --reporter=json
--outputFile=/tmp/jaeger-ui-tests-integrated-final.json` completed with **195 files,
833 tests passed**, zero failed (156.85 seconds). This run includes the frozen
navigation/review fixes and the workspace worker's final TaskBanner race guards.
Report: `/tmp/jaeger-ui-tests-integrated-final.json`; log:
`/tmp/jaeger-ui-tests-integrated-final.log`. Existing React act/key warnings remain.

`git diff --check`: **PASS**. These results do not upgrade destination-level
**PARTIAL** statuses or the browser **BLOCKED** status. Final production build/backend acceptance is recorded separately in the
combined qualification report.


## Later verified scope, still PARTIAL per tab

- Library/Research/Work: the [default report journey](assistant-core-default-report-delivery-20261108.md)
  now exercises real default-mode task admission, one intended approval, native
  tools and independently hashed artifacts through authenticated catalog/download
  and two restarts, including denial after scope drift. The model remains scripted;
  this is not rendered-client or factual research-quality acceptance.
- Research: search URLs and unavailable/no-results states are preserved, but an
  artifact SHA proves bytes, not that citations support the report. The existing
  grounded-citations procedure is not automatically enforced by ordinary research
  task completion. That source-support requirement remains unqualified.
- Settings: [read preservation](assistant-core-provider-settings-preservation-20261108.md),
  [input validation](assistant-core-provider-settings-validation-20261108.md) and
  [revision-bound saves](assistant-core-provider-settings-transaction-20261108.md)
  repair the existing CLI Providers control path using synthetic configurations.
  They do not qualify real CLI accounts or physical Mac/browser behavior.

The latest combined report distinguishes refreshed gates from reused UI evidence.
No unsupported control or tab is promoted to PASS by these scoped results.


- Agents/Work procedure reuse: the [fresh-process qualification](assistant-core-procedure-retrieval-20261108.md)
  proves persisted code retrieval and prompt selection of metadata/references,
  not runtime execution of learned code. Automatic review now reports pending
  verification instead of promoting a merely non-placeholder procedure. Its
  missing objective verifier, caller-verdict and disk-reload trust boundaries
  remain explicit. No tab is promoted to PASS by this correction.


- Chat/Machine/Settings diagnostic scope: the [provider-failure correction](assistant-core-provider-failure-redaction-20261108.md)
  tests recognized credential removal from failed-turn replay/logs and Machine
  log tail while preserving operational receipt data. This is pattern-based,
  synthetic backend qualification, not a universal secrecy or real-account pass.


- Research: the [cooperative HTTP journey](assistant-core-research-journey-20261108.md)
  now covers native retrieval/ledger tools, consistency checking, exact artifact
  download and authenticated Documents persistence. Synthetic providers, lack
  of automatic evidence enforcement and untested interrupted Research status
  keep acceptance PARTIAL.
- Chat/approvals: [complete escaped requested-action display](assistant-core-approval-visibility-20261108.md)
  preserves full supplied details alongside progress previews, marks unsupported
  values unavailable and masks known credentials. Fresh production UI build and
  913 tests in 201 files pass; DOM/CSS evidence is not visual phone/browser QA.


## Current reconciled source qualification

All tabs remain PARTIAL. The current source is documented in
[reconciled qualification](assistant-core-reconciled-qualification-20261108.md).
It preserves prior work and incorporates pinned upstream 315f6ea, with fresh
944-test/205-file UI verification and production build (873 source files,
863 manifest inputs). These are source/DOM checks, not rendered phone/browser QA.

- Chat/navigation: opaque historic IDs, exact links, read/unread state and message
  actions/reactions retain ownership and chronology across authenticated Gateway
  and WebUI routes. Independent namespace and delayed-selection probes pass.
- Research: new explicit contracts enforce designated report/ledger consistency
  and exact checked-result bytes under per-task paths. Legacy tasks are labeled
  unchecked. This does not establish factual truth, authentic retrieval or
  interruption recovery during research.
- Connect Apps: upstream's canonical IDE identity and registry-controlled setup
  are included and tested with synthetic installer boundaries, not an actual
  desktop extension installation.
- Other tabs retain the documented scoped results and unqualified real-account,
  native-host and optional-package limits. No live-runtime pass is inferred.
