> **Classification:** HISTORICAL.
> **Superseded by:** [`docs/CONTINUE_FROM_HERE.md`](../../docs/CONTINUE_FROM_HERE.md) (or `../../../docs/CONTINUE_FROM_HERE.md` from `dev/docs`).
> This is dated evidence. It may reference an old branch, HEAD, dirty worktree, or schedule. Do not treat it as current status, implementation order, or release qualification.

# Jaeger: IDE daily workspace, native controls, interchangeable connections

User direction, 2026-09-23. Product requirement, not a claim of finished backend
integration. Read alongside CAPABILITY_EQUIVALENCE_AUDIT.md and current convergence
evidence. This supersedes the idea that users should choose competing assistant
frameworks as Jaeger's identity or execution owner.

**Priority update, 2026-09-23:** the existing IDE is the daily human interface;
the Mac app provides the menu-bar status/control and Settings only. Native chat,
voice, avatar and pill code remain preserved but hidden behind explicit QA opt-in;
a full native chat redesign remains deferred. Qualify the existing local Jaeger IDE extension
and make bounded transcript/composer improvements, not a new IDE.
Preserve the usable WebUI appearance and repair its conversation lifecycle.
[The master plan](GROK_PERSONAL_RELEASE_PROMPT.md)'s **five-day RC contract** is
authoritative for implementation order. Human IDE use and Jaeger-controlled IDE
workers are distinct; both are part of the intended product. The earlier blanket
worker deferral was too broad. After RC1–RC3, RC7 requires one actual existing
IDE-worker conversation and visible desktop control: task → observed reply →
same-conversation follow-up → independently verified result. Universal provider
support and elaborate dashboards remain deferred. This clarifies the existing
plan and adds remaining effort; the five-day target is not guaranteed. Persona,
voice, useful memory and contextual initiative gates remain in scope.

## Product definition

Jaeger is the persistent reasoning-and-execution system for the operator's
computer. The existing IDE is the daily workspace. Its Mac application is the
native menu-bar/settings control surface; retained chat, avatar, and voice
windows are deferred rather than normal release navigation. The existing WebUI
remains a conversation client. Identity, memory,
responsibilities, run ownership, tools, and outcomes
belong to Jaeger, independently of the selected reasoning provider.

Providers supply interchangeable reasoning capabilities. Existing IDE agent
conversations are the preferred external-agent transport: first Antigravity and
VS Code provider panels. Direct APIs, local models, and CLI agents remain explicit
alternatives, not silent substitutes. An IDE agent is an agent service with its
own context/tools, not a raw model API; represent that distinction honestly.

Two roles for a connected provider session:

- **Reasoning connection:** helps Jaeger decide the next steps for the active
  task. Jaeger retains policy, durable task ownership, tool execution through its
  services, and final outcome verification.
- **Worker connection:** accepts a bounded subtask, performs permitted work with
  its available tools, and returns evidence to its parent Jaeger task. A worker's
  completion claim is not automatically a verified outcome.

```text
Operator → IDE / Web / Mac controls → Gateway-owned Jaeger task
                                         ├─ reasoning connection
                                         ├─ IDE worker connections
                                         └─ Jaeger tools, memory and verification
                                                    ↓
                                         progress and results → Mac / Web
```

## Chat experience

Preservation/design reference, not the next implementation priority. Keep the
initial pass and its tests; fix settings and conversation reliability first.

Use the supplied Codex conversation screenshot as a visual reference, retaining
Jaeger's name and design identity. Priorities:

- Readable, chronological conversation with restrained dark chrome.
- Compact expandable tool/reasoning activity; visible failures even when collapsed.
- Persistent multiline composer, attachments, voice, real model/connection label,
  execution mode, and Stop. Never display a fabricated "Full access" grant.
- Queued follow-ups visible separately from the currently executing task.
- Provider/model names remain distinct from Jaeger's persistent display name.
- The qualified RC worker's events appear beneath their parent task with actual
  connection identity, progress, cancellation, and evidence. No fake active workers.
- Feature navigation stays available on narrow windows without consuming the
  transcript width. Keep settings and existing product capabilities accessible.

The initial SwiftUI pass extracts ChatComposerView and presentation rules from
ChatView; it changes typography, activity disclosure, neutral chat colors, and
toolbar layout. The model picker still uses its existing model configuration
contract. It does not yet select IDE conversations or implement worker orchestration.

## IDE transport integration

Implement the existing DelegateRuntime lifecycle: probe, start, stream, result,
cancel, resume. Reuse the current registry; do not create a second owner/runtime.
Inspect and extend existing `features/ide_orchestration`, Gateway routes and IDE
client methods first. Its current factory wraps CLI subprocess delegates, not
existing IDE panels. Service `_tasks` and `_idempotency_records`, and adapter
`_handles`, are in-memory despite durability wording. Connect the needed records
and recovery to the existing durable owner lifecycle; do not introduce a new
store. The bounded service correction now keeps completed output separate from
verification, freezes retry snapshots, joins concurrent retries, protects terminal
cancellation and rejects unsupported CLI capabilities/read-only claims. Actual
file/test/UI evidence remains required for verification. Gateway HTTP admission
now uses the same snapshot contract and tracks its operations. Durable recovery
remains pending; these isolated HTTP/service tests do not qualify live IDE use.
Bind each connection to its application, workspace, provider panel, conversation,
and chosen role. Prefer supported protocols or extension commands that address
that same conversation, then Accessibility, with vision
for ambiguous UI. Provider availability/model selection must come from observed
state, not hardcoded marketing names or assumed subscription entitlements.
A fresh CLI/App Server thread is a separate worker capability until connection
identity/resume into the actual IDE panel is demonstrated. The current subprocess
delegate `resume` raises `NotImplementedError`; do not present it as continuity.

Submission must preserve multiline text, verify one complete message in the
intended conversation, and avoid blind resend after an uncertain delivery.
Observe working/queued/approval/completed/error states separately. A draft sitting
in the composer or queue is not a delivered and completed task. UI automation must
yield to operator interaction rather than simultaneously type into the same field.

Expose Jaeger tools over the existing MCP integration where supported. Otherwise
use bounded context/result exchange and report unavailable tools. MCP startup and
the local controller must not require a model response from an IDE connection that
cannot initialize until MCP starts. Revisit transport resilience as supported IDE
versions and provider extensions change.

RC7 acceptance: Jaeger sends one bounded task to a selected existing IDE
conversation, observes the actual reply, sends a relevant follow-up there, and
independently verifies the result. Parent-task progress/result appears in the
Jaeger IDE and reopened Web timeline; Mac controls address the same owner.
Qualify Stop, uncertain delivery, quota/login failure and restart without blind
resubmission. General reasoning connections and additional providers can follow.

## Visible computer control and source reuse

Reuse `computer_use_v1`, `macos_computer_v1` and browser tools. Prove fresh
Accessibility/DOM/screenshot observations and actual image delivery to the model
with a randomized visual marker whose answer is absent from text. Display the
active app/target, feedback and Stop; yield to human interaction. A cursor or
target highlight follows real input actions, never fabricated motion during API
calls. Verify target acknowledgment and the resulting task outcome separately.

The coordinator used `mcp__cua_repl`. [The master plan's installed-stack findings](GROK_PERSONAL_RELEASE_PROMPT.md#reuse-decisions-for-this-release)
trace Codex in Antigravity to bundled ChatGPT app resources and the signed OpenAI
computer-use helper with cursor symbols; exact visible frames were not traced.
Evaluate supported, licensed access to that existing stack first. Cua Driver is
a fallback native Accessibility/input/screenshot/overlay candidate, not an
identified component of the installed Codex engine or a finalized dependency.
Its host/overlay must be tested if selected; MCP alone does not supply AppKit
presentation. Open Codex App Server is
a lifecycle/protocol reference and optional worker; Cline is a selective UI/editor
source donor where needed. Neither a browser tool nor an open agent harness
proves all the coordinator's installed computer-use capabilities are included.
Keep the existing Jaeger panel and Gateway. Pin adopted versions, retain license
notices in [DONOR_PROVENANCE.md](DONOR_PROVENANCE.md), and qualify the actual model
and host. The bounded live Ollama comparison is complete: Kilo passed prompts
1–2; Cline passed prompts 1–3 plus restart recovery and is the operational
extension winner on this machine today. Source reuse is a separate decision:
Kilo v7.7.9 is the smaller MIT donor for frame batching and stable-key transcript
projection, while Jaeger retains its Gateway and client contracts. No donor
daemon or provider runtime is adopted. Do not infer native desktop-engine parity
from an extension's working coding tools.
These are candidate integrations, not a completed desktop-control demo.

## Hermes/OpenClaw retirement

The user does not want separate Hermes/OpenClaw assistants required or running on
the machine. This is distinct from preserving useful imported capabilities inside
Jaeger. Resolve exact installed processes/services and dependency callers before
stopping them. Migrate remaining live clients, including any legacy adapter paths,
then demonstrate Web/Mac startup and conversation with those services absent.
Only then remove redundant installations and donor implementations with verified
capability parity. Preserve unrelated software and user data. No process was
stopped, service disabled, installation removed, or live application replaced by
this UI pass.

## Verification of the initial UI pass

Build/test scratch: `/tmp/jaeger-chat-ui.mqrkln/build`.
Component images: `/tmp/jaeger-chat-ui.mqrkln/screenshots/chat-390.png` and
`chat-980.png`. These are offline native SwiftUI render fixtures, not screenshots
of a connected installed app. They exercise real transcript/composer components
with synthetic data and no Gateway/model/voice connection.

Targeted suites: ChatPresentationTests, ChatViewModelTests, TranscriptFeedTests.
Final-source result: **32 tests passed, zero failures, exit 0**. Build and test
output is retained in `/tmp/jaeger-chat-ui.mqrkln/swift-tests.log`.
The tests cover model-label preservation, send eligibility, attachment-only input,
activity labels, component rendering, history mapping, and chronological activity.
Actual installed-app send/stream/cancel, IDE orchestration, and service retirement
remain separate acceptance work. The user's VoiceStage.swift and pre-existing
BridgeProcess/OnboardingFlowTests edits are not part of this UI change.
