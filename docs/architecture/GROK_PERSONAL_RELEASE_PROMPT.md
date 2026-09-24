> **Classification:** HISTORICAL.
> **Superseded by:** [`docs/CONTINUE_FROM_HERE.md`](../../docs/CONTINUE_FROM_HERE.md) (or `../../../docs/CONTINUE_FROM_HERE.md` from `dev/docs`).
> This is dated evidence. It may reference an old branch, HEAD, dirty worktree, or schedule. Do not treat it as current status, implementation order, or release qualification.

# Master personal-release plan: five-day companion-assistant RC

Operator priority, 2026-09-23. This is the implementation entry point for the
personal release. Read and execute it; do not merely critique or rewrite it.

## Current release contract — five-day revision, 2026-09-23

**Authoritative scope and order:** this section replaces the P1–P6 ordering
below for this release. The older sections remain technical/preservation
references, not an additional release checklist. Repository instructions still
apply. Target: a **personal macOS companion-assistant release candidate by
2026-09-28, America/Los_Angeles**, not a public production launch. Five days is
a timebox, not a claim that every remaining feature will fit. Current verdict:
**NOT QUALIFIED**. No new application acceptance tests were run in this planning
revision; source inspection and historical evidence are distinguished below.

### Product promise and change from the previous plan

One persistent Jaeger, with an operator-chosen name/persona and replaceable
reasoning providers, that can talk naturally, remember selected useful facts,
perform real tasks, and initiate a useful update without waiting for a prompt.
IDE sidebar: daily text/work interface. Existing WebUI: continued conversations,
including phone-browser use where the connection is qualified. Mac app: settings,
voice, character presence, notifications and stop/pause controls. No new IDE,
replacement WebUI, or second agent owner.

**Product clarification, 2026-09-23:** Jaeger operating the computer and managing
an existing IDE-agent conversation is part of this same product promise. The
earlier blanket deferral of worker automation was too broad. RC7 now includes
one real worker conversation and visible desktop control, after RC1–RC3. Reuse
the existing extension and open-source components. This adds remaining release
effort; it neither restarts the architecture plan nor guarantees the five-day
target. Voice, persona, memory and contextual initiative remain required.

The Ani reference means **character consistency, voice, visible presence and
responsive interaction**, not a requirement to copy Grok's character, assets,
voice or internal implementation. Use an existing suitably licensed character
or an original operator-approved persona/portrait. An animated portrait/orb is
the RC visual baseline, not full 3D parity. Do not describe a state animation as
real emotion, consciousness, lip-sync, or measured audio amplitude.

The previous plan put voice/presence into P6 and worker transport into P3.
This revision promotes a small voice/persona/presence journey and P5's one
contextual initiative into Must, while moving universal worker support and full
feature-screen wiring after the RC. One bounded worker/control journey is now
required under RC7. Keep useful backend convergence work, but
only release-path defects block this timebox. Nothing deferred is permission to
delete its source, skills, endpoints, assets or intended capabilities.

### Starting point: what exists versus what is proven

Audit baseline: branch `next/clean-app`, HEAD `917e1eb8`, substantial staged,
unstaged and untracked work. Recheck before editing; a commit hash alone does
not identify this candidate. Do not overwrite the staged 0.9.3 roadmap or the
operator's `VoiceStage.swift` changes.

| Area | Evidence available | RC gap |
| --- | --- | --- |
| Gateway and Web | Real isolated Chromium: 20 turns, long Markdown, cancel/first next send, reload, narrow-screen send passed with scripted provider. Malformed-attachment rejection, owner-computed file hashes, cancel admission/terminal ordering and dashboard asset isolation are repaired. | Configured live-provider acceptance; all final-source regression checks; physical phone/off-LAN journey. Do not redo repaired omissions or count scripted replies as model-quality proof. |
| IDE sidebar | Local extension exists; provider/model forwarding, explicit settings-versus-session choices, refresh and activity-state logic reviewed with 59 offline/reviewer passes (1 skip); owned-Gateway integration passed. | Final Antigravity interaction with a configured provider. Current Gateway SSE does not publish tool progress; synthetic activity tests do not prove it. Arbitrary external-file import remains absent; workspace file registration works. |
| IDE orchestration and desktop control | Existing service, Gateway routes, IDE client methods, DelegateRuntime, computer-use skills and browser tools are reusable. The bounded correction separates completed from verified, protects terminal cancellation, compares full retry snapshots, joins concurrent retries, applies awaited-operation deadlines and rejects unsupported CLI read-only/existing-panel capabilities. Gateway HTTP now validates/forwards the snapshot and tracks the admitted operation. | Records/handles still live in memory; integrate with the existing durable owner lifecycle. Default adapters remain one-shot CLI, not existing IDE conversations. Require actual file/test/UI verification and image delivery proof. Turn/cost budget enforcement remains pending. |
| Mac settings | Current Swift code includes configured-secret status and backend read-back; catalog Path serialization was repaired. External debug app and signature check passed; Swift rerun: 162 executed, 3 skipped, no failures. | Installed-candidate settings interaction and effective-versus-saved behavior. No native GUI or physical audio qualification from the build/test pass. |
| Persona | `features/personality` supplies character loading/composition; Gateway `_si_character_prompt` and `_si_soul_prompt` use the instance. | Verify the selected persona reaches the actual enabled owner turn, across clients/restart/provider changes. A helper existing is not live wiring proof. |
| Voice | `features/voice/session.py` submits through Gateway; Swift has STT/TTS managers. Voice README reports prior 20–35 s entity turns and experimental barge-in. | Physical microphone/playback, same-session context, latency, reliable stop, no self-transcription or double speech. README timings are historical, not a measurement on this candidate. |
| Presence | `Avatar/VoiceOrbView.swift` loads a face and derives idle/thinking/speaking from bridge/TTS state; waveform is procedural. | Actual offline/listening/error state. `AvatarWindows.swift` mic toggle currently persists configuration, not live capture. Do not label that toggle a functioning microphone. |
| Proactivity and memory | Lease-based background producers, memory services and delivery mechanisms exist. Earlier audit found no production cognition-handler registration. | One observed-source → contextual decision → durable work → actual notification journey, plus selected-fact retention/forgetting. Recheck the selected path rather than implementing all cognition experiments. |
| Packaging/accounting | Local VSIX packaging exists. Shared external Swift build/CLI discovery and an actual debug `.app` build are verified. Source-freshness fix complete: `_swift_source_fingerprint` replaces wrong git-diff approach; `build-source-hash` stamp written pre-build. 35 freshness unit tests pass. Web missing-usage reporting changed from zeros to explicit unknown. | Rebuild with new stamp required (Bash blocked during qualification session); stale=False runtime confirmation pending; combined required test suites not re-run. A consumer reading `usage` does not prove the owner emits it. |

Historical WebUI browser and process reports cover different source snapshots.
Do not collapse their counts into a final-source pass. The latest supplied IDE
screenshot shows `fetch failed`; it alone does not establish the cause or the
current daemon state. Diagnose endpoint, process, authentication and selected
instance before changing UI or starting/restarting operator services.

### Must ship: bounded capabilities and acceptance

Latest implementation evidence: [continued browser/build audit](CURRENT_PRODUCT_AUDIT.md#continued-implementation-and-actual-browser-audit--2026-09-23).
The isolated real-browser 20-turn/long-response/cancel/reload journey and an
external debug `.app` build now pass. Provider inference was scripted; native
GUI/audio, final IDE host, remote phone and the other RC journeys remain open.
Do not repeat the old “no actual app built” or “HTTP calls only” findings, and do
not use this bounded proof to certify live-provider or physical-device behavior.

All nine gates below are **pending final-candidate qualification**. Existing
component tests may reduce work, but do not pre-check these gates.

| Gate | Smallest acceptable scope | Required proof |
| --- | --- | --- |
| RC1 — launch and one owner | Existing launchers; one instance; actionable provider/Gateway status; no silent local-agent fallback on enabled product paths. | Fresh external state, launch IDE/Web/Mac, provider unavailable/retry, owned daemon restart. Distinguish `/health` success from model readiness. |
| RC2 — reliable conversation | Streaming, Markdown, correct chronology, attachments, stop, approvals, history/reconnect. Preserve Web appearance; bounded IDE improvements only. | 20 consecutive distinct turns in one session with contextual follow-ups; browser and IDE each exercised; phone-browser layout checked; one file received by ID/content hash and absent on next turn; deny/approve; EOF/error; cancel then first next admission without hidden 409 retries; session isolation. |
| RC3 — truthful settings | Name/persona, provider/model, voice, source/autonomy enablement, quiet/pause controls through existing catalog/services. | Save/reopen, normalized read-back, invalid/offline save, masked configured secrets, saved versus applied/restart-required labels, next turn using correct settings. No old response overwrites a newer edit. |
| RC4 — character continuity and useful memory | One chosen persona, consistent voice/style, selected explicit facts and one standing responsibility. Shared retrieval, not merged transcripts. | Recall a test fact in a new chat/other client after restart; inspect/correct/forget it using existing memory interface/tools; subsequent new-chat retrieval excludes forgotten fact. Old transcript content is distinct from active memory. Provider change does not rename/reset Jaeger. |
| RC5 — usable voice | One qualified STT/TTS pair in the Mac experience, push-to-talk, visible transcript, voice/text fallback, explicit stop for audio and active turn. | 10 physical spoken exchanges, context follow-up, mic denial, playback failure, stop/retry, no echo-loop or double playback. Measure speech-end → first audible answer, not the call to `speak()`. See responsiveness budget below. |
| RC6 — simple visible presence | Existing face/orb plus accurate connected/listening/working/speaking/error signals and mute/stop. | Observe actual state transitions with working and unavailable audio/Gateway; no busy animation after completion. No new 3D engine required. |
| RC7 — useful agency, worker control and initiative | Read a selected project/file; perform one approved sandbox file task; use one real existing IDE-worker conversation with visible desktop action feedback; monitor one operator-selected local task/source. Existing producers and delegates remain subordinate to the owner. | Deliver a bounded task once, observe the actual reply, send a contextual follow-up in the same IDE conversation, independently verify its result, and retain parent-task progress through reconnect/restart. Observe active-target feedback, Stop and yielding to human input. With chat closed, a relevant change prompts model-assessed useful contact; irrelevant change stays quiet; duplicate stays single; pause/quiet hours respected; notification opens durable result; restart retains responsibility. Neither a timer greeting nor scripted worker output passes. |
| RC8 — understandable control/cost | Real permissions, Stop/Pause, bounded background model calls/time, actionable failures; usage measured or explicitly unknown. | Budget exhaustion halts new background inference; unknown usage is not $0; no unauthorized paid/outgoing action; no secrets in evidence; prototype screens cannot claim successful real operations. No new security framework. |
| RC9 — installable, repeatable candidate | Local VSIX, external `.app`, existing Web launcher, exact version/diff manifest, enablement list and rollback instructions. | Final artifacts—not only development hosts—pass the golden journey and relevant regressions. No repo runtime/build state, no operator-state access in tests. Installation/activation of live operator services remains a separate authorized step. |

RC2 cross-client continuity means reopening the same Gateway-owned timeline from
IDE and Web, with identical accepted messages and outcomes. Mac settings/voice
must address the same entity/instance. Opening a new focused chat need not replay
every transcript; selected memory remains shared. Simultaneous chat concurrency
must not blend histories. Automatic forks/context orchestration is not required.

**RC7 implementation boundary:** inspect current extension → Gateway routes →
`IDEOrchestrationService` → DelegateRuntime/adapter wiring before adding code.
Extend those owners; do not create another scheduler, task store or agent loop.
Bind the worker to the actual application, workspace, provider panel and
conversation. Prefer a supported worker protocol when it addresses that same
conversation; otherwise use existing Accessibility/vision transport. A newly
started CLI thread is useful separately but does not prove steering the user's
existing IDE panel. Record delivery, observed response, follow-up, cancellation,
login/quota failure and uncertain delivery; never blindly resend uncertain work.

Desktop actions need fresh Accessibility/DOM or screenshot observations, plus
proof the selected vision model receives actual image content: use a fresh
randomized visual marker whose answer is absent from the text observation.
Confirm the actual UI target acknowledged input; independently inspect output.
Owner restart must retain identity without duplicate resubmission. Show the active
application/target and working/stopped/error state; a cursor or target highlight
should follow actual actions. Stop must halt pending input and control must yield
to the human. Do not animate pretend mouse movement for protocol/API work. The
coordinator's demonstrated tool was `mcp__cua_repl`; the installed helper below
contains cursor support, although individual drawn frames were not traced.
Reproduce the observable experience using supported
components, without claiming that Codex's open-source harness includes every
computer-use capability available in this coordinator session.

### Reuse decisions for this release

Keep Jaeger's existing IDE panel, streaming presentation, Gateway, DelegateRuntime,
`ide_orchestration`, computer-use skills and browser tools. **Audit the current
installed stack first**, then evaluate supported, licensed access to its existing
capabilities. Repair missing contracts before installing a replacement or adding
a subsystem. The candidates below are not finalized architectural dependencies.

**Inspected installed stack, 2026-09-23:** Antigravity IDE 2.5.5 Electron/Plugin
Host launches its installed Codex extension 26.908.40401 and bundled CLI
0.154.0-alpha.6.2. The live computer-use process ancestry reaches the Node runtime
bundled in `/Applications/ChatGPT.app/Contents/Resources/cua_node/` and `node_repl`.
The installed `unified-computer-use` plugin 26.908.70816 launches
`@oai/cua-repl` 0.1.0 with `@oai/cua` 0.2.4 and `@oai/sky` 0.6.32. Its signed
OpenAI helper at `~/.codex/computer-use/Codex Computer Use.app` (26.913.1001067,
`com.openai.sky.CUAService`) contains `ComputerUseCursor`, `FogCursorStyle` and
`SoftwareCursorStyle` symbols. This supports attributing cursor capability to
the helper, without proving the provenance of every visible frame. The user is
operating Codex inside Antigravity; it also uses native resources from the installed
ChatGPT app. The computer-use plugin is proprietary; no open-source grant was
identified for these `@oai` runtime components. Their presence is not proof of
a supported Jaeger integration or copying rights. `trycua` is not established as
this implementation. Check existing supported integration and licensing before
selecting any replacement; keep native-control acceptance unchanged.

| Component | Decision and boundary | Adoption proof |
| --- | --- | --- |
| [Cua Driver](https://github.com/trycua/cua/blob/main/libs/cua-driver/README.md), [MIT license](https://github.com/trycua/cua/blob/main/LICENSE.md) | Fallback native desktop donor candidate if the inspected installed stack cannot supply a supported, licensed integration. Not identified as the current Codex engine. Provides macOS Accessibility, screenshots/input and [session-colored cursor/action feedback](https://github.com/trycua/cua/blob/main/libs/cua-driver/docs/cursor-themes.md). Prefer a pinned dependency or supported adapter over a project copy if selected. | Complete current-stack evaluation first, then pin/review version and notices; native Mac smoke test, model image receipt, active-target feedback, Stop/yield. The AppKit overlay needs a suitable host such as `CuaDriver.app` or supported embedding; MCP-only operation does not supply it by itself. Local compatibility remains untested. |
| [Codex CLI/harness/App Server](https://github.com/openai/codex), [Apache-2.0 license](https://github.com/openai/codex/blob/main/LICENSE), [protocol docs](https://learn.chatgpt.com/docs/app-server) | Streaming lifecycle/protocol reference and optional supported Codex worker adapter under Jaeger ownership. It does not automatically supply the installed proprietary extension UI or all computer-control tools. | Match exact protocol version, retain notices, map task/events/cancel/result to existing owner contracts. A new App Server thread is not an existing IDE conversation unless identity/resume interoperability is demonstrated. |
| [Cline](https://github.com/cline/cline), [Apache-2.0 license](https://github.com/cline/cline/blob/main/LICENSE) | Selective UI/editor integration donor only where Jaeger has a proven gap; [Antigravity installation](https://github.com/cline/cline/blob/main/docs/getting-started/installing-cline.mdx) and [Ollama/LM Studio/cloud connections](https://github.com/cline/cline/blob/main/docs/getting-started/authorizing-with-cline.mdx) are documented. Preserve current panel and owner. | Review selected source/version/notices and test the adapted interaction. Browser automation is not proof of native desktop control. No wholesale extension fork or broad donor bakeoff before RC7. |

These are source-backed reuse candidates, not completed integrations. Preserve
attribution/version records in [the existing donor ledger](DONOR_PROVENANCE.md).
Model quality, vision and tool-call reliability
remain separately qualified; changing harnesses does not promise Astra-level
reasoning from every local or cloud model.

**Latest authorized next step:** install Cline and Kilo locally, compare their
actual Ollama tool use in an external disposable workspace, and use that evidence
to choose any donor integration into the existing Jaeger extension. This bounded
comparison is explicitly authorized; the earlier “no broad bakeoff” limit does
not prohibit it. Do not record a winning donor until measured results exist.
The coordinator assigns one UI controller at a time; other agents can repair
independent Jaeger boundaries concurrently. Current-stack provenance remains
the basis for computer-control reuse; these extension trials do not establish
that either supplies the installed OpenAI native computer-use engine.

Bounded orchestration verification on this source: existing runner's focused
unit file **30 passed, 2 integration deselected**; its integration tier **2 passed,
30 deselected**; both exit 0. Ruff passed for the owned feature/test Python files;
the changed Gateway handler range and tracking annotation had zero diagnostics.
The integration uses a deterministic worker and owned Gateway, not live provider
or desktop control. Records are still process-local; no RC gate is certified.
Current built-in CLI delegates cannot enforce read-only mode, so default
`read_only=true` tasks are now blocked rather than silently receiving write access.

**Responsiveness budget:** aim for first audible answer within 5 seconds on
ordinary warm conversational turns; proposed RC ceiling is median ≤5 s and p90
≤10 s over the 10 measured short exchanges. Report device, provider, sample size
and cold-start time separately. Visible listening/working feedback should appear
within 1 s; explicit Stop should silence playback within 1 s in those trials.
These are product targets, not current measurements or statistically strong
performance claims. Tool-heavy tasks may take longer with genuine progress.
Repeated 20–35 s silence fails the companion-experience gate. Try existing
provider/routing settings and a bounded conversational path **inside the owner**;
do not bypass policy or invent a second voice agent. If needed, stream speakable
sentences from owner events using existing TTS, with cancellation and deduplication
tests. Do not promise natural full-duplex barge-in; push-to-talk + Stop is the RC.

**On-the-go boundary:** qualify one existing authenticated private connection on
the operator's phone if remote use is claimed. Test actual off-LAN reconnect and
retained history. Keep the raw Gateway loopback-only; do not expose :8810 publicly
or build a new auth stack this week. Without that test, release notes must say
local/LAN only, and travel-ready status remains blocked even if desktop RC passes.

### Put on hold for this release

| Deferred work (retain code/intention) | Why it is not a five-day dependency | Re-entry gate |
| --- | --- | --- |
| Full Hermes absorption, monolith extraction, mass folder reorganization, global configuration injection and full legacy migration | Large blast radius; fresh isolated state is acceptable; preserve working behavior. Fix specific release-path leaks now. | After RC baseline, resume convergence milestone-by-milestone with parity tests. Separate Hermes/OpenClaw services must not be required for the enabled RC path. |
| Universal IDE-provider support, general MCP/A2A orchestration and elaborate worker dashboards | One existing IDE conversation plus visible desktop control is required in RC7; expanding to all providers is beyond that slice. | After the RC7 task → reply → same-conversation follow-up → independent verification journey passes, add providers individually with transport/failure proof. |
| Full 3D/Live2D body, custom rigs, precise lip-sync, emotion simulation, character marketplace | Presence already has a reusable surface; animation cannot repair voice latency. | RC5–RC6 accepted, then select licensed asset/runtime with a measured performance budget. |
| Always-on listening, wake words and natural full-duplex barge-in across every client | Audio/device routing risk; push-to-talk is an honest smaller experience. | Physical-device interrupt/echo/permission tests before enablement. |
| Full native Skills/Tasks/Kanban/Workspace/finance/device UI parity | Preserve existing Web/tool access; simple controls and a durable result view suffice now. | Wire one real owner-backed vertical slice at a time; keep demos visibly separate meanwhile. |
| Automatic session forks, multi-character societies, universal hive-memory sharing | Shared selected memory and resumable timelines satisfy immediate continuity without context leakage. | Define task/memory scopes and owner contracts after current journeys pass. |
| Self-rewriting/installing the running app, autonomous repairs with live activation | Current release first needs stable tools, isolated repair workspace and repeatable UI proof. | Reproduce → bounded patch → tests → UI replay → separately authorized activation. |
| Broad robotics/hardware operation, all providers/voices, public distribution, benchmarks and exhaustive platform hardening | Not required for this one-operator Mac release; high qualification cost. | Separate release targets and platform-specific acceptance. |

Should/could only after all Must gates are green: better IDE model picker and
attachment previews, speech convenience in Web, richer activity cards,
additional worker transports and notification channels. One qualified existing
IDE-worker conversation and visible desktop action feedback are already Must.
Current-model and
attachment-success visibility are already Must; elaborate picker/card designs
are not. Never display an Undo/fork/worker control without its real backend.

### Five-day execution and stop rules

No assumption of unlimited agent credits or three concurrent implementers.
Use one coordinator and one active writer per boundary. Named agents below are
possible assignees, not a claim that Claude/Gemini/Codex accepted work. If more
than one agent is actually available, parallelize independent UI/audio work only
after agreeing shared contracts and file ownership. Otherwise execute serially.

| Window | Deliverable / accountable role | Exit and contingency |
| --- | --- | --- |
| Day 1: Sep 23–24 | Coordinator/runtime owner: short delta review; launch/provider diagnostic; final-source Web/IDE conversation and cancel/upload defects; early physical voice latency probe; inspect existing worker routes/transport and native driver availability. | Stable basic answer and identified audio/worker dependencies. If not, stop UI decoration and fix exact producer. Establish source/file ownership before edits. |
| Day 2: Sep 24–25 | Client owner: finish RC1–RC3, minimal IDE Markdown/activity and external Mac packaging. Once RC1–RC3 pass, begin RC7's existing-worker/desktop slice using current adapters and selected donor. | Browser/IDE multi-turn and effective Mac settings pass; worker target and durable-owner integration contract established. If blocked, record schedule impact; do not quietly drop worker/control acceptance. |
| Day 3: Sep 25–26 | Voice/persona owner: RC4–RC6; reuse current persona, orb, STT/TTS and memory surfaces. | Physical voice and continuity demo with measured latency. If blocked by hardware/provider or latency, mark companion release at risk; do not count scripted audio as a pass. |
| Day 4: Sep 26–27 | Runtime/delivery owner: complete RC7 worker task/reply/follow-up/result proof and visible native control; contextual initiative, pause/budget, cross-client/restart and selected remote access qualification. | Real IDE worker and useful outreach proven; durable responsibility/task identity retained. Start feature freeze; no additional providers/features. A missing worker or initiative journey remains a failed gate. |
| Day 5: Sep 27–28 | Release verifier: final artifacts, golden journey, relevant broad regressions, a two-hour mixed-use soak, launch/rollback evidence. | Only blocker fixes and their replays. Ship scoped RC only if all Must pass. Otherwise deliver a clearly labelled preview with failed gates, not a fake completed companion release. |

Front-load external dependencies on Day 1: selected live provider and allowed
test spend, physical mic/speaker permissions, available STT/TTS models, chosen
persona/asset rights, phone/private access if wanted. Record missing access in
one list and continue independent work. Do not silently buy services/download
large models or restart the operator's working IDE/services.

Keep Day 5 as verification/buffer. RC7 now explicitly includes the remaining
worker transport and desktop-control integration effort. Re-estimate after its
bounded donor/transport probe; five days remains a target, not a completion
promise. Do not add another audio engine or 3D renderer to rescue the schedule.
If gates miss, offer the working text/voice subset as a preview and give the
exact remaining blockers; the five-day target does not authorize weakening tests.

### Golden journey and evidence ledger

From packaged clients and a fresh owned instance: select name/persona/provider;
send and follow up in IDE; continue the same conversation in Web; upload a small
file and inspect actual content receipt; deny then approve harmless sandbox work;
cancel and send again; ask Jaeger to delegate a bounded task into a real existing
IDE-worker conversation, observe its reply and a contextual follow-up, inspect
the independently verified result, and exercise visible native control/Stop/yield;
speak and stop audio in Mac; save one fact/responsibility;
close chat; trigger a relevant monitored change; receive/open the useful update;
restart owned services; recover history, fact and responsibility; forget the fact
and verify new-chat retrieval. Exercise provider down and stream drop, not only
happy paths. Remote-phone claim requires the additional off-LAN run above.

Record per RC gate in CONVERGENCE.md: `not_run / pass / fail / blocked_external`,
source commit **and dirty-diff/artifact fingerprint**, exact command/environment,
exit code/skips, screenshot or interaction log, provider (scripted/live), state
root and remaining limitation. Do not log secrets/private transcripts. Keep logs,
builds and screenshots outside the source tree. A report of another agent's
pass is labelled reported until its artifact/source identity is checked.

Use targeted runner tests between changes, then relevant unit/integration,
production-path/security, Swift and IDE tests at candidate freeze. Reuse existing
tiers; no full lint migration of donor code. Run the actual browser and installed
candidate after fixes. A click, HTTP 200, compilation, synthetic screenshot, or
test count alone does not prove that an answer appeared or audio played.

### Agent continuation prompt

> Implement the five-day RC contract at the top of this master plan, not the
> historical P1–P6 order. Read AGENTS.md and current diffs; preserve all existing
> work, especially the staged roadmap and VoiceStage.swift. Inspect only the
> next relevant boundary and CONVERGENCE.md's latest evidence. Claim files before
> sharing a checkout with another writer. Reuse existing Gateway, clients,
> persona, memory, audio, background producers, DelegateRuntime, ide_orchestration,
> computer_use_v1, macos_computer_v1 and browser tools. Use the bounded donor
> order above: trace the installed Codex/Antigravity computer-use stack and evaluate
> supported/licensed reuse first; Cua Driver remains a fallback candidate. Use open
> Codex App Server contracts for a supported worker, and selective Cline source only
> for an identified UI/editor gap. Preserve licenses and pin adopted versions.
> Start with Day 1 startup,
> final-source conversation verification, and the early voice latency probe.
> Repair root causes with focused regressions and actual UI replay. Continue
> through the Must gates while safe authorized work remains; do not stop after
> scaffolding or demand a new prompt for each test. Defer the explicit Hold list.
> After RC1–RC3, complete RC7's actual existing IDE conversation: task, observed
> reply, contextual follow-up and independent file/test/UI verification. Integrate
> in-memory service/adapter records with the existing durable owner lifecycle;
> nonempty worker output is not verification. Prove fresh observations and image
> delivery, active-target feedback, Stop/yield and reconnect/restart handling.
> A new CLI thread or fake worker fixture does not qualify an existing IDE panel.
> Do not delete capabilities, reset live data, start competing agents, rewrite
> the WebUI, change protected edits, commit/push or activate a replacement live
> installation. Use external builds/state and the existing isolated test runner.
> If live access, spend or OS permissions are missing, request that precise input
> and continue independent work. Record pass/fail/blockers and source/artifact
> identity in CONVERGENCE.md. Do not claim a companion release without voice,
> character continuity, useful initiative, real worker/desktop control and the
> packaged-client evidence. This clarification adds work; report schedule risk
> rather than dropping a Must gate or rewriting the plan again.

## Historical execution order — settings-first revision, 2026-09-23

This section retains the prior P1–P6 decomposition for technical reference.
The five-day release contract above now controls scope and implementation order.
The detailed older contracts remain preservation references, not prerequisites
to completing every small release slice. Evidence and exact audit commands:
[CURRENT_PRODUCT_AUDIT.md](CURRENT_PRODUCT_AUDIT.md#settings-first-audit-update--2026-09-23).

### Scope decision

- Use the existing IDE for daily human work. Do not build another IDE.
- Prioritize Mac **settings and operational controls**, not further chat styling.
  Preserve the existing chat implementation and its regression tests.
- Preserve the WebUI appearance. Diagnose and repair the actual composer-to-owner
  lifecycle. A plausible backend cause is not a diagnosed two-turn crash.
- Reuse the catalog, model router, Gateway, bridge, delegate lifecycle, tools,
  and background producers. Rewrite a defective boundary when necessary; no
  repository-wide rewrite or folder reorganization as an opening move.
- Distinguish a usable operator checkpoint from a proactive-assistant release
  and from full architectural convergence. All three have different gates.
- Fresh isolated state remains acceptable. Do not reset live operator state.

### Evidence-backed starting point

| Area | Current evidence | What is still missing |
| --- | --- | --- |
| Web composer | Fresh owned-process test passes two streamed replies and history retrieval through `/api/chat/start`; scripted model | Real browser reproduction, distinct answers/context retention, recovery and attachment/approval parity |
| Owner lifecycle | Fresh focused producer/admission/cancellation/mind tests pass; model-selection process tests pass | All product callers using one owner; live-provider and cross-client qualification |
| Mac settings | Schema-derived catalog, validation, persistence, Swift controls, bridge commands exist; Python catalog/CLI tests pass | Visible load failures, effective runtime state, read-back, configured-secret status, actual settings interaction |
| IDE workers | Existing CLI delegate adapters and lifecycle | Persistent IDE-panel transport not established; common subprocess `resume` explicitly unsupported |
| Native delivery | Source opts bridge into Gateway mode; earlier offline UI tests exist | External `.app` packaging and actual connected settings journey; build script still uses in-repo `.build` |
| Proactivity | Lease-gated producers, sensors, memory and delivery code exist | Observed-source → cognition → owner task → useful outreach journey; no production cognition-handler registration found |
| Feature screens | Existing Web features and native prototypes retained | Native sample screens must not imply real actions; full wiring may follow operator checkpoint |

Fresh audit: 70 focused tests passed, exit 0; 4 selected owned-process tests
passed, 26 deselected, exit 0. No graphical UI or live model was exercised.
Earlier composer history assertion failure was a test-envelope error; another
agent corrected it. Do not classify that earlier failure as proven data loss.
Source is being edited concurrently: recheck relevant diffs before implementation.

### Ordered milestones and bounded assignments

Effort is relative, 1–5 (5 largest), not hours or credit estimates. Characterize
the named boundary before changing it; do not rerun the whole audit each time.

#### P1 — reliable existing WebUI conversation (effort 3, uncertainty medium)

Scope: `features/webui/api/gateway_chat.py`, actual route/stream/approval callers,
browser session handling where evidence points, Gateway contracts and owned tests.
Dependency: current isolated harness and stable request/terminal-event contract.

1. **P1a: characterize the reported failure.** Extend the existing composer test
   to five distinct expected replies in one session, including a follow-up that
   needs earlier context. Assert distinct request IDs, exact history, no duplicate
   execution, reload/reconnect and cancel-then-next-turn. A cancel HTTP `ok` alone
   is not terminal cancellation. Drive the same sequence in the actual browser;
   correlate client session/stream IDs with Gateway request/events. Preserve the
   failure evidence. Stop this assignment with a reproduction and root-cause
   location, or an explicit not-reproduced result and narrowed test coverage.
2. **P1b: repair adapter parity at its producer.** The inspected Jaeger adapter
   accepts but does not forward attachments, omits computed reasoning overrides,
   initializes usage to zero, and can emit `done` after stream EOF without seeing
   a terminal event. Protect and correct these contracts in bounded changes.
   Inspect approval response round-trip and tool-progress translation; raw
   approval emission is not proof of a working Approve button. Use existing
   admission/attachment/approval services, not a second execution path.
3. **P1c: qualify and close.** Exercise first/next turn, stream interruption,
   provider failure, real cancellation receipt, harmless tool, attachment,
   approve/deny, refresh/reconnect, session switching and owned restart. Compare
   Web history with owner history. Repair duplicate storage/projection ownership
   at the boundary if it causes drift. Verify documented launcher defaults, not
   just environment overrides supplied by a fixture.

Exit: deterministic contracts plus real browser actions show expected answers
and durable matching outcomes; no false success on EOF or busy-state lockout.
Live configured-model verification is separate and requires appropriate access.
Non-goals: new WebUI, donor monolith decomposition, chat redesign, vendor deletion.

#### P2 — Mac settings control the running assistant (effort 3, uncertainty medium)

Scope: `MenuCard/SettingsStore.swift`, `AgentSettingsHUD.swift`, bridge settings
commands, `core/settings/catalog.py`, relevant config consumers, build launcher.
Dependency: stable owner identity/config target. P2a can proceed independently
of P1b when a single agent completes one assignment at a time.

1. **P2a: truthful settings state.** Characterize catalog failure, invalid values,
   normalized backend values, secret configured/unconfigured status, and rapid
   successive edits. Show loading/retry/errors. Use the backend's returned value
   or authoritative read-back rather than assuming the submitted value is final.
   Keep secrets masked; don't add credential stores or duplicate schemas.
2. **P2b: saved versus applied.** Map each immediate setting to its actual owner
   and consumer: connection/model defaults, enabled autonomy, permissions, budget
   and delivery controls. Prove persistence and effective behavior separately.
   Mark settings needing owner restart accurately. Do not tell the user merely
   to reopen the Mac client when the independent Gateway needs reconfiguration.
   Preserve an in-flight request's admitted model/options during later edits.
3. **P2c: package and exercise.** Fix external Swift build/output and launch
   discovery together. Build an owned `.app` outside the checkout; open actual
   settings against an isolated owner. Verify save/reopen, invalid save, offline
   owner, restart-required state, no edits to another instance, and changed
   behavior in the next appropriate Web/Gateway operation.

Exit: settings show configured, connected, saved and effective state honestly;
changes survive reopen/restart and control the intended owner. No new native
chat design or full Skills/Tasks/Kanban/Workspace implementation required here.

#### P3 — minimum IDE/worker integration (effort 4, uncertainty high)

Human IDE use is already possible and does not depend on implementing this.
Jaeger controlling an IDE agent is a separate capability. Inventory supported
local transports without invoking paid agents, and reuse DelegateRuntime.
Choose one installed provider/IDE connection with the operator before live use.
Do not represent CLI one-shot calls as persistent IDE-panel conversations.

Assignment: implement one scoped connection bound to workspace and conversation;
prove one multiline task is delivered once, progress/result are associated with
the parent task, and a follow-up uses the same conversation where supported.
Characterize cancellation, unavailable/login/quota states, uncertain submission,
and budget reporting. Do not blindly resend after an uncertain UI submission.
Exit: an observed task/result round trip plus failure tests, with unsupported
resume explicitly shown. No assumption that a subscription provides API access.
Non-goals: integrations with every provider, another IDE, a second Jaeger owner.
If this needs unavailable access, do not block P4's existing-interface checkpoint.

#### P4 — usable operator checkpoint (effort 2, uncertainty medium)

Dependencies: P1 and P2; P3 only for claims of Jaeger-controlled IDE workers.
Verify Web conversation + Mac settings operate the same isolated instance,
retain new memory/history, survive disconnect/owned restart, and show connection
failures. Keep basic native chat regression checks; do not require its redesign.
Verify no competing local runtime silently starts in the enabled release path.
Keep intentional standalone embedding explicit and separate.

Expose prototype tabs as demo/not connected and prevent simulated success claims
until wired; do not delete their intended capabilities. Document exact launch
commands, external app artifact, enabled features, limitations, test evidence,
and separately authorized activation/rollback. Full live-model claims need a
bounded configured-model journey, not a scripted provider. Exit: usable scoped
operator release, not a claim of full proactivity or architectural convergence.

#### P5 — proactive-assistant qualification (effort 4, uncertainty high)

Dependency: reliable owner and P2 controls; retain the contextual journey in
historical Milestone 2 below. Connect one enabled observation and standing
responsibility through existing owner admission to an existing delivery channel.
Prove relevant action, irrelevant silence, duplicate suppression, pause/budget,
chat-closed outreach and new-chat/restart continuity. No canned greetings or new
parallel reasoning daemon. Required before calling the product a demonstrated
proactive assistant; not required to hand over the earlier usable checkpoint.

#### P6 — preserved follow-on work (larger, split by owner before estimating)

Retain feature-to-surface wiring, voice/hardware qualification, richer IDE workers,
vision/interactive-terminal parity, and observed reproduce → repair → replay
self-maintenance. Existing browser/screenshot repairs are in progress; recheck
them rather than reproducing stale audit defects. Keep separate from remaining
architecture work: instance configuration injection, complete catalog ownership,
WebUI extraction, Hermes absorption, all-client cutover and full release suites.
Fresh-state release does not require exhaustive old-history migration, mass
folder moves, or new hardening frameworks. Essential permission/state isolation,
request identity, cancellation and honest outcome reporting remain required.

### Immediate handoff and change log

Historical next assignments were **P1a**, **P1b**, **P2a**. Each handoff includes current
file hashes/diffs, exact test command, expected result and explicit stop gate.
Check relevant changes before taking over a concurrently edited file. Work one
bounded assignment at a time; continue safe implementation without requiring a
fresh user prompt after every test. Record failures as well as successes.

This revision promotes Mac settings over chat appearance; keeps the existing IDE
and WebUI; separates human IDE use from new worker transport; replaces the old
all-clients/all-features gate with explicit operator/proactive/convergence gates;
and incorporates fresh two-turn evidence without declaring the reported crash
fixed. The staged 0.9.3 roadmap and user source changes are untouched.

The sections below retain broader behavior and preservation requirements. Their
milestone numbering is historical; select work from the current RC contract.

For direct browser/macOS black-box interaction and repair, also execute
[`UI_EXPLORATORY_AGENT_PROMPT.md`](UI_EXPLORATORY_AGENT_PROMPT.md).

## Mission

Work in `/Users/matthewjenkins/GitHub/JaegerAI`.

Deliver a reliable existing WebUI and native macOS settings/control surface,
using the existing IDE for daily work, connected to one persistent Jaeger
execution owner. Then complete a genuine proactive workflow
and the intended feature interfaces. Implement, run, inspect, and fix the result.
Do not substitute another plan, scaffolding, fake UI data, or unit-test counts
for a usable application.

The operator wants an assistant, not a chatbot. Chat windows are views onto an
ongoing entity; they are not its lifecycle. Jaeger maintains goals, commitments,
new memories, and background work across chats and restarts. It observes sources
the operator enables, judges relevant changes, initiates useful work, contacts
the operator when warranted, and knows when to stay quiet. It knows its available
tools, permissions, connections, and limitations. This is operational awareness,
not a claim of consciousness or access to information it has not observed.

It should eventually improve its own skills and workflows, and develop tested
tool/code improvements. Preserve those intended capabilities. Do not let a new
self-modification framework delay working clients. Use existing extension/skill
mechanisms first; code improvements belong in an isolated workspace, with tests
and an authorized activation step, not silent rewrites of the running owner.

## Scope and precedence

Read root and applicable nested AGENTS.md instructions. Then read:

1. `docs/architecture/CONVERGENCE.md`, latest entries first.
2. `/tmp/jaeger-convergence.nJEGqw/CHECKPOINT.md`, if still available.
3. Relevant sections of `docs/architecture/RELEASE_AGENT_PROMPT.md` for the selected
   task's technical contracts and U01–U06; do not reload the whole historical
   specification for every bounded assignment.
4. `docs/OPERATIONS.md` for existing operational behavior.

This prompt sets personal-release priority where the older master plan makes
all architecture work a prerequisite. Preserve its valid behavior contracts.
The full convergence backlog still exists; label deferred work honestly.
Check the current worktree delta rather than assuming any checkpoint is current.
Do not redo the entire repository audit or read every donor file before coding.

Fresh runtime state is acceptable. Old chat history, learned memory, and old
receipts do not need migration. NEW memory and continuity must work. Preserve
code, features, skills, tools, and useful configurations; a fresh build does not
mean discarding the repository or changing UI frameworks. Do not import pending
actions, schedules, or historical permission grants implicitly.

Use a separate fresh state root outside the checkout. Leave operator state
untouched initially. Before any later authorized reset, resolve exact targets,
preserve important or uncertain material in a verified dated Desktop archive or
retain its original source. No plaintext credential exports. No blind copies of
active SQLite files. Coordinate live cutover separately; no broad deletion.

## Current progress to preserve

Rounds 1–6 implemented admission snapshots, cancellation/approval recovery,
streaming, opt-in bridge-to-Gateway execution, owner-side continuation, tool
restrictions, attachment/display/subordinate field forwarding, and other
configuration/tool/migration primitives. Do not rebuild these.

Round 7 added lease-gated cron, idle/heartbeat, and webhook composition through
`core/runtime/background_producers.py`. Round 8 added a Gateway-backed mind/window
runtime. `create_runtime` prefers Gateway, then bridge, then local boot; this
does not yet prove that every product entrypoint has only one execution owner.
Separate deliberately supported standalone embedding from product fallback.

Round 9 fixed the four bounded background correctness findings listed in the
previous revision: changed-input background request IDs conflict, webhook board
creation is delivery-idempotent, producer shutdown closes admission and joins
cron/idle before releasing its lease, and failed cron admission restores the
claimed occurrence. Focused producer/admission tests recorded 31 passed, exit 0.
Do not repeat this work unless a current regression reproduces.

The Swift `BridgeProcess.launchEnvironment` now sets
`JAEGER_BRIDGE_EXECUTION=gateway` unless explicitly overridden. This makes the
NEXT Mac app build launch its bridge as a Gateway client; it is not proof of a
live Swift conversation or a repository-wide default cutover. The installed
`/Applications/JaegerAI.app` was not rebuilt/restarted. Only one offline Swift
launch-environment test ran (1 passed, external scratch `/tmp/jaeger-swift-r9`).

Latest recorded Round 8 owned-process run: 29 passed, exit 0. Round 6/7 focused
and production-path runs passed, but older full-unit/package/Swift results do
not qualify newer edits. Round 7's full-file run printed 28 passes AND an
isolation failure; a pytest pass count does not override a nonzero session exit.

The prior operator-tree fingerprint changes still need test-process attribution
if they recur; do not assume either test leakage or harmless operator activity
without proof. This is a bounded isolation check, not permission to begin another
hardening program. Continue directly to real-client delivery.

## Milestone 1 — actual working WebUI and Mac app

Reference contracts: use P1–P4 above for current ordering. Complete meaningful
vertical slices without asking for a new prompt.

### Startup and execution

- Trace real Swift BridgeProcess, WebUI proxy, Gateway, bridge, and launcher
  configuration. Use existing transports and SDKs; do not build replacement UIs.
- `apps/macos` and `apps/web` alias the actual client directories. Authoritative
  code is `jaeger_ai/interfaces/swift` and `jaeger_ai/features/webui`.
- `jaeger gateway daemon` runs Jaeger Gateway, normally :8810, health `/health`.
  Bare `jaeger gateway` manages a different external service. WebUI normally uses
  :8790. Tests use explicitly configured owned ports/sockets, not operator ones.
- Build the Mac app outside the source tree. Fix build/launch discovery together
  so the produced app is actually launchable, without replacing the operator app.
- Both clients must use the same configured instance and canonical owner.
  An unavailable Gateway must show a useful connection error, not secretly boot
  another product agent. Preserve explicit standalone embedding separately.
- Make startup straightforward with the existing entrypoints: documented exact
  commands, actionable model/provider setup, and visible connection status.
  No new installer/service-manager framework unless a concrete blocker needs it.

### Required user journeys

Exercise the actual browser and shipping Swift client against owned services:

1. Fresh onboarding, chosen name/persona, model/provider selection.
2. Send a message; see incremental response; cancel an in-flight turn.
3. Start a new chat and reopen saved history without mixing sessions.
4. Upload/select a file; verify the intended file reaches the turn.
5. Execute a harmless real tool in a temporary workspace; inspect the result.
6. Approve/deny an action through the actual UI; cancellation closes approval.
7. Refresh/reconnect one client and use the other without losing owner state.
8. Restart owned services and recover new history and terminal outcomes.
9. Exercise existing voice input/output where the host supports it. Separate
   audio-device/model/OS-permission blockers from code failures. Text still works.

Preserve non-chat bridge functionality: settings, onboarding, voice controls,
and existing feature commands. Do not call one successful chat full parity.

The Mac source already opts its bridge into Gateway execution. After relevant
parity passes, finish other product launch paths/defaults and remove competing
product local-execution branches. Keep this a source and owned-instance cutover;
do not restart the operator's live installation.

Milestone 1 output: a launchable external `.app`, working local WebUI, exact
startup instructions, interaction evidence, and explicit remaining limitations.
Report this usable checkpoint promptly and keep working on the next milestone.
If only scripted model tests passed, say so; that is transport qualification,
not evidence of a live model-backed assistant.

## Milestone 2 — demonstrate proactive assistance, not canned messages

Reuse existing goals/missions, memory, event, scheduler, heartbeat, tool, and
delivery services. Map the specific journey's owners; do not invent an adjacent
framework because an existing module is unfamiliar.

The minimum complete journey:

1. Operator sets a standing responsibility and enables an observation source.
2. With no new chat message, a relevant change reaches the resident owner.
3. The model assesses it against the responsibility and current context.
4. It takes an authorized useful action, asks a needed question, or stays quiet.
5. A useful update reaches the operator outside the originating conversation.
6. New-chat/restart continuity retains the responsibility and outcome.

Use a safe local example: monitor a chosen temporary project/task for a blocker
or completed artifact, inspect the change, and decide whether follow-up matters.
Do not implement a special-case “send this greeting every N minutes” behavior.
Events/timers may deterministically wake reasoning; the action decision must be
contextual. Test a relevant change, an irrelevant change, and duplicate delivery.

Wire at least one existing real delivery channel that can reach the operator
with the chat window closed: e.g. native notification, with a durable activity
inbox as the readable record. An SSE event with no listener is not delivery.
If the entire Mac process exits, distinguish queued delivery on reopen from a
separately running notifier. Do not promise notifications a stopped process
cannot produce. Keep Gateway work alive independently of UI windows.

Expose simple controls: standing responsibilities, connected sources, pause,
quiet hours, allowed actions, and resource budget. Build these into existing
settings/work/activity surfaces. Do not prompt for approval on every harmless
already-authorized observation. Retain meaningful controls for consequential
actions; autonomy is not permission expansion.

Use cheap event checks and bounded reasoning. No unbounded continuous model loop.
Show concise reasons/evidence for actions, not invented awareness or hidden
chain-of-thought. Test freshness, unavailable sources, and silence decisions.

## Milestone 3 — finish feature wiring and capability access

Complete the existing UI, rather than adding one tab per backend module.

Known Swift prototypes to inspect:
- SkillsView: sampleCatalog.
- TasksView: sampleTasks.
- KanbanView: sample board.
- WorkspaceView: sample snapshot and simulated commit behavior.

Replace sample data/actions with authoritative services and real receipts.
Fixtures belong in previews/tests, not normal screens. Unavailable operations
must explain what is missing; disabling everything is not completed wiring.

Preserve existing Web skills/memory/cron/workspace panels, finance dashboard and
intents, model/settings, extensions, connections, and voice features. A shared
backend does not require every client to have identical layouts. Give intended
capabilities a clear accessible entrypoint, truthful status, and actual action
where implemented. Clearly separate planned capabilities from available ones.

Preserve autonomy, reflection, cognition, skill learning, delegation, and device
intent. Unused code is not by itself permission to delete the desired behavior.
Connect or replace implementations as needed. Defer new speculative mechanisms
that do not help a current user journey, and record them rather than concealing
their status. Use U01–U06 in the broader master prompt as a coverage reference.

## Essential verification, without overengineering

Use focused tests during each substantial change. At milestone boundaries run
relevant broader suites, Swift tests, and actual browser/client interactions.
Use `dev/scripts/run_tests.sh`; inspect its options. Use external Swift scratch
paths and isolated HOME/state/workspaces. Preserve credentials outside logs.

Always capture the process exit code, skips, and isolation failures. Do not weaken
tests to claim success. Investigate leaks with process-scoped instrumentation or
access denial; do not inspect the operator's private databases to diagnose tests.
Live-tree fingerprints alone cannot attribute concurrent writes to a process.

Regression essentials: no lost new state, one execution owner, real cancellation,
intended permissions, no duplicate actions, truthful UI outcomes, restart and
reconnect, and no test access to operator state. Inspect the diff and callers
before declaring a slice complete. Include actual UI interaction evidence;
screenshots alone and offline Swift compilation do not establish working APIs.

Use scripted providers for repeatable tests, visibly distinguished from real
inference. A real configured model smoke test is needed for live AI claims.
If it requires paid calls, credentials, model downloads, OS permissions, or
external communication not already authorized, ask one precise question and
continue independent work. Do not pretend that a simulator proves judgment.

Defer exhaustive historical migration, mass folder reorganization, new security
frameworks, perfect lint/type coverage of donor code, and complete vendor removal
when they do not block these milestones. Preserve essential controls and tested
working implementations. Never declare full convergence just because the personal
release works. Later architecture work remains explicitly tracked.

## Working rules and finish conditions

- Preserve dirty/staged work, especially VoiceStage.swift and the staged
  `dev/docs/roadmap/0.9.3_EVERYDAY_AGENCY_PLAN.md`. Do not commit/push/reset/stash.
- Use one agent unless explicitly authorized otherwise. Do not overlap another
  writer in this checkout. Keep usage controlled with focused inspections/tests.
- No operator-service restarts, live DB modification, blanket deletion, real
  outgoing messages, hardware operation, or paid calls without relevant authority.
- Keep application/build/test state outside the repository; use apply_patch for
  edits. Maintain feature documentation and valid public contracts.
- Keep moving from one verified slice to the next. Do not stop at scaffolding,
  each small milestone, or another plan while safe authorized work remains.
- Before usage expires, update CONVERGENCE.md and an external checkpoint with
  exact changes, tests/exit codes, blockers, launch commands, artifact paths,
  enabled/default status, and the next executable task.

Deliver usable applications, not just code:
1. The WebUI and Mac app launch and complete the required real client journeys.
2. One contextual proactive workflow works without a new user message, has a
   visible outcome/notification, and survives reopening a chat.
3. Intended feature screens are wired or accurately itemized as unfinished;
   no production sample data masquerades as reality.
4. Fresh-state installation/startup is documented and reproducible.
5. Remaining integration/hardware/provider checks and broader convergence work
   are explicit. Do not label blocked acceptance as a passed release.

Start with a short current-delta inspection and the next current RC assignment.
Do not spend the next implementation session rewriting this plan, redesigning
chat, or redoing already verified work without a reproduced regression.
