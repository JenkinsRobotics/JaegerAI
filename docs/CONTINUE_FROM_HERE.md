# Continue from here — current Jaeger continuation state

**Classification:** CURRENT AUTHORITATIVE
**Branch:** `pinocchio`
**Baseline at audit start:** `4124422b15e7f0ca28941774992000b24a151719`
**Date:** 2026-09-24
**Branch rule:** work on `pinocchio`; do not modify or merge `master` unless the operator explicitly asks.

This is the single execution entry point for humans and coding agents. Old branch audits, five-day plans, and phase trackers are evidence, not status. Re-read the current source before acting.

## Read first

1. This file.
2. [`AGENTS.md`](../AGENTS.md) — engineering doctrine, state isolation, and topology.
3. [`architecture/ARCHITECTURE.md`](architecture/ARCHITECTURE.md), [`architecture/MAIN_LOOP.md`](architecture/MAIN_LOOP.md), and [`architecture/STATE_OWNERSHIP_MAP.md`](architecture/STATE_OWNERSHIP_MAP.md).
4. [`architecture/TEST_ARCHITECTURE.md`](architecture/TEST_ARCHITECTURE.md) before claiming what a test proves.
5. The current source owners named in the backlog item you are changing.

## Product target

One persistent Jaeger entity with:

- one Gateway-owned execution path;
- reliable IDE and WebUI clients using the same owner and durable sessions;
- truthful provider, model, and tool capability reporting;
- real tool execution, approvals, effect records, and independent verification;
- reliable Stop/cancel and immediate next-turn admission;
- reconnect and restart durability;
- selected durable memory and persona continuity;
- usable Mac voice and presence;
- bounded proactive work;
- one real existing IDE-worker conversation Jaeger can steer;
- a phone/field client using the same Jaeger identity and state, not a second mobile assistant.

The model is replaceable cognition. The client is not the entity. A tool returning success is not the same as a verified effect. A scripted UI pass is not a live-provider qualification.

## Proven today

“Proven” means current source plus the named current or recent evidence. It does not mean release-ready.

| Claim | Current evidence | Evidence level |
| --- | --- | --- |
| Gateway owns durable sessions, request receipts, approvals, and multi-client SSE replay | `jaeger_ai/core/gateway/session_store.py`; `jaeger_ai/core/gateway/event_bus.py`; `dev/tests/jaeger_ai/core/test_gateway_durability.py`; `test_gateway_session_unification.py`; `test_gateway_owned_process_contract.py` | Owned-process and integration tests |
| WebUI defaults to the Gateway; its session store is a read-through mirror of Gateway sessions | `jaeger_ai/features/webui/api/gateway_chat.py::webui_chat_backend_mode`; `api/gateway_mirror.py`; `test_one_execution_path.py`; `test_gateway_mirror.py`; `test_gateway_stream_admission.py` | Source and unit/integration tests |
| WebUI hides legacy Hermes-only tabs and offers only the `jaeger` profile unless `JAEGER_LEGACY_PATHS` is set | `jaeger_ai/contract/legacy_paths.py`; `features/webui/api/config.py`; `static/boot.js` | Source-backed; needs a dedicated regression if this becomes release-critical |
| IDE client exists and speaks only the Gateway REST/SSE contract | `jaeger_ai/interfaces/ide/gateway.js`; `conversation.js`; `extension.js`; `dev/tests/jaeger_ai/core/test_ide_gateway_client.py`; `interfaces/ide/tests/*.test.js` | Node and owned-Gateway integration tests |
| Tool, reasoning, plan, file-change, approval, and shell output events are represented and streamed in order | `core/gateway/server.py::_turn_stream_callbacks`; `interfaces/ide/media/timeline.js`; `features/webui/static/messages.js`; `test_gateway_tool_events.py`; `test_gateway_stream_admission.py` | Unit/integration tests; live tool cards still need end-to-end proof |
| Human actionable turns default to the resident ReAct/tool loop, not a model-only bypass | `core/gateway/server.py::_execute_turn`; `core/entity/runtime.py::run_subordinate_react`; `packages/jaeger-agent/jaeger_agent/loop/jaeger_agent.py::run_turn`; `test_runtime_truth.py`; `test_control_plane_consolidation.py`; `test_gateway_single_terminal.py` | Source and production-path tests |
| Explicit image-question and text-only/specialist lanes exist at the Gateway boundary | `server.py::_execute_turn`; `test_gateway_single_terminal.py` | Source and unit tests; they are not silent fallbacks |
| Recent Chromium qualification exists for multi-turn, long output, cancellation, reload, and narrow viewport | `test_gateway_owned_process_contract.py::test_owned_browser_multiturn_render_cancel_and_reload` | Owned-process Chromium with a scripted provider; not live-provider or physical-phone proof |
| Swift/macOS source, external build path, and test suite exist | `interfaces/swift/Package.swift`; `Scripts/build-app.sh`; `Tests/JaegerAITests`; `test_external_swift_build.py` | Source and Swift tests; installed-app/GUI remains unqualified |
| Gateway-owned live steering exists and the IDE uses it for the active ReAct request; an honest no-agent 409 returns `false` instead of creating a local queue | `/v1/sessions/{id}/requests/{request_id}/steer`; `core/entity/runtime.py::run_subordinate_react(on_agent=...)`; `interfaces/ide/gateway.js::steer`; `interfaces/ide/conversation.js::steer`; `test_gateway_live_steering.py`; `interfaces/ide/tests/steering.test.js` | Unit tests; still needs live-provider and real IDE-worker acceptance |
| Gateway owns the durable session queue; the IDE exposes `Queue next`, edit, reorder, pause/resume, and delete without owning a second task store | `/v1/sessions/{id}/queue*`; `core/gateway/session_store.py::enqueue_request/promote_next_queue_item`; `interfaces/ide/gateway.js`; `interfaces/ide/media/view.js`; `test_gateway_session_queue.py`; `interfaces/ide/tests/queue.test.js` | Source and unit tests; not live-provider or installed-host qualified |
| Gateway-enforced plan-only turns exist: the IDE Plan toggle and `/plan` command grant only `update_plan`, so file, shell, and browser tools are not admitted | `allowed_tools=["update_plan"]`; `packages/jaeger-agent/jaeger_agent/tools/plan.py`; `interfaces/ide/media/view.js`; `interfaces/ide/extension.js`; `test_gateway_admission_snapshot.py::test_plan_only_grant_is_frozen_and_replayable`; `interfaces/ide/tests/plan.test.js` | Source and unit tests; still needs live-provider and installed-host acceptance |
| IDE context chips and `/diagnostics` project the active file, selection, open files, and bounded workspace problems without creating a second context owner | `interfaces/ide/commands.js::buildIdeContext`; `extension.js::ideContext/diagnosticsSnapshot`; `media/view.js::renderContextChips`; `media/slash-commands.js`; `interfaces/ide/tests/context.test.js` | Source and unit tests; installed-host/live-provider acceptance remains open |
| IDE session tabs support close, reopen, and durable client-side ordering while the Gateway remains the session owner | `interfaces/ide/conversation.js::openSessionIds/closeSession`; `media/view.js::renderSessionTabs`; `interfaces/ide/tests/sessions.test.js` | Source and unit tests; installed-host/live-provider acceptance remains open |
| IDE workspace selection is explicit, persisted per Gateway endpoint, and sent through the Gateway admission `workspace` field for new chats, immediate turns, and queued turns | `interfaces/ide/extension.js::restoreWorkspace/selectWorkspace`; `media/view.js`; `interfaces/ide/tests/extension.test.js::test_explicit_workspace_selection_reaches_the_Gateway_admission_body`; `interfaces/ide/tests/workspace.test.js` | Source and unit tests; installed-host/live-provider acceptance remains open |
| IDE `@` file mentions pick a workspace file and stage it through the existing Gateway attachment contract before the next turn | `interfaces/ide/extension.js::mentionFile`; `interfaces/ide/conversation.js::addAttachment`; `media/view.js`; `interfaces/ide/tests/mention.test.js`; `interfaces/ide/tests/extension.test.js::test_@_mention_stages_the_picked_workspace_file_through_the_Gateway_attachment_contract` | Source and unit tests; installed-host/live-provider acceptance remains open |
| Large iOS client tree exists | `apps/ios` (451 tracked files) with chat, SSE, auth, attachments, voice notes, live activity, watch, and share extension | Donor/current tree only: it is Hermes-branded, targets Hermes `/api/chat/*`, and contains no Jaeger references |
| Runtime capability reporting is grounded in configured/reachable state, not marketing labels | `core/runtime/truth.py`; `core/entity/model_capabilities.py`; `/v1/runtime/models`, `/v1/runtime/capabilities`; `test_runtime_truth.py`; `test_cognition_profiles.py` | Source and unit tests; configured live-provider check remains open |
| Bridge clients default to Gateway execution and fail closed when the Gateway is unavailable | `interfaces/bridge.py::gateway_execution_enabled`, `_attach_gateway`, `_gateway_turn`; `interfaces/test_bridge.py` | Source and bridge protocol tests |
| Product runtime adapters now fail closed when no owner is available; `GatewayRuntime` routes real bus approvals and calls the request-scoped Gateway steering route | `core/mind_runtime.py::create_runtime`; `core/runtime/gateway_runtime.py`; `core/gateway/client.py::steer`; `test_gateway_mind_runtime.py` | Source and unit tests; live-provider and installed-host acceptance remains open |

## Not yet qualified

No live-provider, physical-device, or final installed-artifact qualification is claimed in this audit.

1. **Live configured-provider conversation.**
2. **End-to-end tool + approval + effect + independent verification.**
3. **Stop/cancel during a live tool/streaming phase, then immediate next-turn admission, reconnect, and restart.**
4. **IDE and WebUI same-session continuity.**
5. **Real existing IDE-worker conversation steering.**
6. **Durable memory add/recall/correct/forget.**
7. **Persona continuity across provider/model changes.**
8. **Physical microphone/speaker voice qualification.**
9. **Truthful runtime presence states.**
10. **One real proactive workflow with dedupe, quiet hours, and persistence.**
11. **Phone/off-LAN field client using the same Jaeger identity and sessions.**
12. **Final installable artifact qualification.**

## Priority order

- **P0 — reliable live conversation/execution path**
- **P1 — IDE + WebUI as the same Jaeger**
- **P2 — memory/persona/voice/presence**
- **P3 — phone/field client**
- **P4 — bounded proactive agency**

## Prioritized remaining work

### P0-1 — Live configured-provider conversation

- **Problem:** No current turn has been qualified through the enabled owner with a real configured provider. Scripted tests prove transport and routing, not live provider behavior.
- **Current evidence:** `test_gateway_owned_process_contract.py` uses a scripted provider; `test_runtime_truth.py` proves capability reporting but not a live provider call.
- **Affected files/owners:** `core/gateway/server.py`; `core/entity/runtime.py`; `core/models/external_model.py`; `core/models/router.py`; provider adapters under `packages/jaeger-agent/jaeger_agent/adapters/`; WebUI/IDE clients.
- **Acceptance test:** Start an isolated Gateway with a real configured provider, send a human turn, verify the provider/model reported by `/v1/runtime/models` is the provider/model that executed, stream the answer, persist one terminal receipt, reload the session from another client, and restart the owner without duplicate execution.
- **Priority:** P0.
- **Type:** integration.

### P0-2 — Stop/cancel and immediate next turn

- **Problem:** Cancellation is tested with scripted/owned-process providers, but not during a real provider/tool phase with live streaming and immediate next-turn admission.
- **Current evidence:** `test_request_cancellation.py`; `test_gateway_owned_process_contract.py::test_owner_cancellation_interrupts_inflight_provider`; `test_gateway_cancel_confirmation.py`.
- **Affected files/owners:** `core/runtime/cancellation.py`; `core/gateway/server.py`; `jaeger_agent/loop/jaeger_agent.py`; `interfaces/ide/conversation.js`; `features/webui/static/messages.js`; `interfaces/swift/.../AmbientLoop.swift`.
- **Acceptance test:** Run a real configured-provider turn, issue Stop during a tool or streaming phase, verify exactly one terminal `cancelled` outcome, confirm no pending approval remains, immediately admit the next turn without hidden 409/retry, then reconnect and restart the Gateway.
- **Priority:** P0.
- **Type:** integration.

### P0-3 — Tool, approval, effect, and verification chain

- **Problem:** Tool execution and approval contracts exist, but a live provider/tool chain with an independently verified effect is not yet qualified.
- **Current evidence:** `test_gateway_owned_process_contract.py::test_real_tool_write_requires_gateway_approval`; `test_gateway_tool_events.py`; `core/effects`; `PolicyKernel`.
- **Affected files/owners:** `core/gateway/server.py::_GatewayToolConfirmationProvider`; `packages/jaeger-agent/jaeger_agent/tool_executor.py`; `core/authority`; `core/effects`; verification probes.
- **Acceptance test:** Through a live provider, request a bounded file/process effect, require approval, approve it, verify the changed state independently of the tool result, record the effect and verification chain, then deny the same request in another run and verify no effect occurred.
- **Priority:** P0.
- **Type:** integration.

### P0-4 — Product-path runtime live qualification

- **Problem:** The unit-level adapter defects are repaired, but the repaired path still needs live-provider and installed-client acceptance.
- **Current evidence:** `create_runtime` now raises an explicit diagnostic when no Gateway or bridge owner is available; `GatewayRuntime` routes approvals through the real bus, reports unsupported approvals instead of hiding a deny, and calls the request-scoped Gateway steering route. `test_gateway_mind_runtime.py` passes 9 focused tests.
- **Affected files/owners:** `core/mind_runtime.py`; `core/runtime/gateway_runtime.py`; `core/gateway/client.py`; client bus/approval surfaces.
- **Acceptance test:** Start an isolated Gateway with a configured provider, request a gated effect, approve it through a real client surface, independently verify the effect, then steer a live tool/streaming turn through the same route and immediately admit the next turn after Stop.
- **Priority:** P0.
- **Type:** integration.

### P1-5 — IDE and WebUI same-session continuity

- **Problem:** Mirror and client contracts exist, but a live cross-client journey has not been qualified on the current baseline.
- **Current evidence:** `features/webui/api/gateway_mirror.py`; `interfaces/ide/conversation.js`; `test_gateway_mirror.py`; `test_ide_gateway_client.py`.
- **Affected files/owners:** Gateway session/event store; WebUI mirror; IDE client; Swift Gateway client.
- **Acceptance test:** Create one session in the IDE, send a turn, reopen it in WebUI, continue it there, return to the IDE, restart both clients and the Gateway, and verify identical accepted messages, outcomes, event order, and selected provider/model.
- **Priority:** P1.
- **Type:** integration.

### P1-6 — Real existing IDE-worker conversation steering

- **Problem:** Gateway live steering is implemented for the resident ReAct agent and `GatewayRuntime` now calls the request-scoped owner route, but no real existing IDE-worker conversation has been steered end to end.
- **Current evidence:** `test_gateway_live_steering.py`; `interfaces/ide/tests/steering.test.js`; `core/runtime/gateway_runtime.py`.
- **Affected files/owners:** `features/ide_orchestration`; worker adapters; Gateway orchestration records; IDE client.
- **Acceptance test:** Select an existing IDE worker conversation, send a bounded task, observe its actual reply, steer it with a relevant follow-up in the same conversation, independently verify the result, and retain parent progress through reconnect/restart.
- **Priority:** P1.
- **Type:** integration.

### P2-7 — Durable memory add/recall/correct/forget

- **Problem:** Memory subsystems and projection code exist, but the user-facing add/recall/correct/forget journey is not qualified across clients, restart, and provider change.
- **Current evidence:** `core/entity/memory.py`; `core/entity/runtime.py::prepare_turn/finish_turn`; `jaeger_agent/memory`; memory tools and tests.
- **Affected files/owners:** EntityRuntime; SemanticMemory; memory tools; WebUI/IDE/Mac clients.
- **Acceptance test:** Add a synthetic explicit fact through one client, recall it in a new chat from another client after owner restart, correct it, verify the corrected value is used, forget it, and verify later retrieval excludes it.
- **Priority:** P2.
- **Type:** integration.

### P2-8 — Persona continuity across provider/model changes

- **Problem:** Identity and character composition exist, but selected persona continuity across live provider/model changes and restart is not qualified.
- **Current evidence:** `core/entity/identity.py`; `features/personality`; Gateway character/SOUL prompt helpers; `test_prompt_identity.py`; `test_runtime_truth.py`.
- **Affected files/owners:** EntityIdentity; personality feature; model router; Gateway prompt composition.
- **Acceptance test:** Change provider/model on a live owner, restart it, and verify entity ID, display name, selected persona, prompt composition, and style remain stable while the reported provider/model changes.
- **Priority:** P2.
- **Type:** integration.

### P2-9 — Physical microphone/speaker voice qualification

- **Problem:** Voice source and tests exist, but physical input/output, audible latency, stop, and failure states are unqualified.
- **Current evidence:** `features/voice`; `interfaces/swift/Voice`; `AmbientLoop.swift`; `test_voice_session.py`; `AmbientLoopTests.swift`.
- **Affected files/owners:** VoiceSession; Swift STT/TTS; `AmbientLoop`; `VoiceRecorder`; `TTSManager`.
- **Acceptance test:** Complete at least 10 physical spoken exchanges, measure speech-end to first audible answer, verify contextual follow-up, mic denial, playback failure, Stop/retry, no self-transcription, and no double playback.
- **Priority:** P2.
- **Type:** hardware + integration.

### P2-10 — Truthful runtime presence states

- **Problem:** Presence UI exists, but live connected/listening/working/speaking/error state transitions are not qualified.
- **Current evidence:** `AmbientLoop.swift`; `Avatar/VoiceOrbView.swift`; `AvatarWindows.swift`; `interfaces/swift/README.md`.
- **Affected files/owners:** Swift ambient state; Gateway event stream; voice/audio state; Mac UI.
- **Acceptance test:** Observe actual state transitions with working and unavailable audio/Gateway, verify no busy animation after completion, no fake microphone state, and explicit errors when audio or Gateway is unavailable.
- **Priority:** P2.
- **Type:** integration.

### P3-11 — Phone/off-LAN field client

- **Problem:** `apps/ios` is a substantial donor client, but it is Hermes-branded, targets Hermes WebUI endpoints, and has no Jaeger identity/session wiring. It is not the Jaeger field client yet.
- **Current evidence:** `apps/ios/HermesMobile/Networking/Endpoints.swift` uses `/api/chat/*`; `rg -i jaeger apps/ios` returns no matches; 96 iOS test files exist.
- **Affected files/owners:** `apps/ios/HermesMobile/Networking`; `Features/Chat`; branding/onboarding; Xcode project and tests; Gateway client contract; `dev/scripts/remote_phone_acceptance.py`.
- **Acceptance test:** Retarget the client to Gateway `/v1/sessions/{id}/turns` and SSE, use the same entity/session as desktop, prove off-LAN reconnect and retained history, test Face ID/passkey and native photo picker, and run a live provider turn on a physical phone.
- **Priority:** P3.
- **Type:** code + integration + hardware.

### P4-12 — One real proactive workflow

- **Problem:** Background producers, heartbeat, task ownership, and notification code exist, but no real observation → decision → durable work → notification journey is qualified.
- **Current evidence:** `core/runtime/background_producers.py`; `core/entity/sensors`; `GatewayTaskOwner`; `core/runtime/background_delivery.py`; `docs/gateway-task-ownership.md`.
- **Affected files/owners:** EntityRuntime cognition handler registration; SensorSupervisor; GatewayTaskOwner; notification/delivery tools; quiet-hours settings.
- **Acceptance test:** Select one real observation source, prove a relevant change creates one durable task and one useful notification, an irrelevant change stays quiet, a duplicate stays deduplicated, quiet hours suppress it, and the responsibility/task/result survive restart.
- **Priority:** P4.
- **Type:** integration.

### P4-13 — Final installable artifact qualification

- **Problem:** External Swift build and packaging paths exist, but no final `.app`/VSIX/WebUI artifact set has passed a clean golden journey.
- **Current evidence:** `interfaces/swift/Scripts/build-app.sh`; `interfaces/ide/package_extension.py`; `scripts/run-jaeger-webui.sh`; `test_external_swift_build.py`.
- **Affected files/owners:** Swift build script; IDE packaging; WebUI launcher; installer; `jaeger` launcher.
- **Acceptance test:** Build final external artifacts from a clean state, install/activate them without touching live operator state, run the golden live-provider journey and relevant regressions, record rollback steps, and verify no runtime state in the repository.
- **Priority:** P4.
- **Type:** packaging + integration.

## Explicitly deferred

Do not spend current release effort on:

- full Codex UI parity;
- every slash command;
- universal worker/provider support;
- full Hermes donor removal;
- elaborate dashboards;
- 3D/avatar polish;
- automatic reflect-to-skill generation;
- exhaustive legacy-state migration;
- another architecture rewrite.

Preserve useful source and evidence for deferred work, but do not treat a deferred feature as a release blocker or a reason to create a second owner.

## Continuation rules

- Inspect current code and tests before acting.
- One fact has one authoritative owner.
- No second Gateway, runtime, scheduler, task store, or memory owner.
- No compatibility shims.
- No duplicate files or copied implementations.
- No runtime state in the repository.
- Unit tests alone are not capability claims.
- Distinguish **scripted**, **owned-process**, and **live-provider** evidence.
- Preserve user data and live services.
- Prefer small verified repairs over parallel frameworks.
- Do not silently fall back to another execution path.
- Do not remove legacy code unless its reachability and safety are proven.
- Do not claim physical-device or live-provider readiness without the corresponding acceptance evidence.

## Current runtime path

```text
IDE / WebUI / Mac / TUI
    → Gateway REST + SSE (:8810)
    → JaegerGatewayApp.handle_send_turn / handle_add_queue
    → GatewaySessionStore.admit_request / promote_next_queue_item
    → Gateway._execute_turn
    → EntityRuntime.prepare_turn
    → EntityRuntime.run_subordinate_react
    → build_jaeger_agent
    → JaegerAgent.run_turn
    → model → tools → model → answer
    → EntityRuntime.finish_turn
    → GatewaySessionStore.complete_request
    → GatewayEventBus durable SSE
    → clients
```

Audit findings:

- The WebUI’s in-process runner, native profile runner, and the Gateway native-MCP-first lane are isolated behind `JAEGER_LEGACY_PATHS`.
- The bridge defaults to Gateway execution and fails closed if the Gateway is unavailable; `JAEGER_BRIDGE_EXECUTION=local` is an explicit diagnostic mode.
- Image-question and text-only/specialist lanes are explicit at the Gateway boundary, not hidden model-only fallbacks.
- Gateway live steering forwards text to the active resident ReAct agent and returns 409 for a text-only or unbound request. The IDE reports “Queue next”; queued work is a durable Gateway `client_request`, never a client-owned queue.
- The product runtime adapter now fails closed when no owner is available, routes Gateway approvals through the real bus, and steers the active Gateway request; live-provider and installed-client qualification remain open.
- The Swift app has both a bridge client and direct Gateway client code; both must remain clients of one owner and one session projection.
- The iOS tree is donor/current source, not a Jaeger client yet.

## Planning document classification

| Document | Classification | Action |
| --- | --- | --- |
| `AGENTS.md` | CURRENT AUTHORITATIVE | Engineering doctrine and topology |
| `README.md` | CURRENT REFERENCE | Operator overview; points here |
| `docs/README.md` | CURRENT REFERENCE | Documentation index; points here first |
| `docs/CONTINUE_FROM_HERE.md` | CURRENT AUTHORITATIVE | This file |
| `docs/OPERATIONS.md` | CURRENT REFERENCE | Runtime state, upgrades, recovery |
| `docs/gateway-task-ownership.md` | CURRENT REFERENCE | Gateway durable task ownership |
| `docs/EXTENSION_GUIDE.md` | CURRENT AUTHORITATIVE | Public extension contracts |
| `docs/architecture/ARCHITECTURE.md` | CURRENT AUTHORITATIVE | Topology and ownership |
| `docs/architecture/MAIN_LOOP.md` | CURRENT AUTHORITATIVE | One turn path |
| `docs/architecture/STATE_OWNERSHIP_MAP.md` | CURRENT AUTHORITATIVE | State owners |
| `docs/architecture/TEST_ARCHITECTURE.md` | CURRENT AUTHORITATIVE | Test tiers and proof boundaries |
| `docs/architecture/THREAT_MODEL.md` | CURRENT AUTHORITATIVE | Security model |
| `docs/architecture/DONOR_PROVENANCE.md` | CURRENT REFERENCE | Donor attribution |
| `docs/architecture/adr/` | CURRENT REFERENCE | Accepted decisions |
| `docs/architecture/CURRENT_PRODUCT_AUDIT.md` | REMOVED FROM ACTIVE TREE | Dated 2026-09-23 evidence; preserved in Git history |
| `docs/architecture/MASTER_PROGRAM_STATUS.md` | REMOVED FROM ACTIVE TREE | Old architecture program and old baseline; preserved in Git history |
| `docs/architecture/GROK_PERSONAL_RELEASE_PROMPT.md` | REMOVED FROM ACTIVE TREE | Old five-day plan and old branch evidence; preserved in Git history |
| `docs/architecture/RELEASE_AGENT_PROMPT.md` | REMOVED FROM ACTIVE TREE | Old convergence prompt; preserved in Git history |
| `docs/architecture/IDE_FIRST_PRODUCT_DIRECTION.md` | HISTORICAL | Useful product requirements and old worker direction |
| `docs/architecture/CAPABILITY_EQUIVALENCE_AUDIT.md` | HISTORICAL | Capability matrix and acceptance ideas |
| `docs/architecture/CODEX_PARITY_BACKLOG.md` | BACKLOG / DEFERRED | Selective parity work only |
| `docs/architecture/CONVERGENCE.md` | REMOVED FROM ACTIVE TREE | Dated convergence evidence; preserved in Git history |
| `docs/architecture/RELEASE_AUDIT.md` | REMOVED FROM ACTIVE TREE | Old release audit; preserved in Git history |
| `docs/architecture/UI_EXPLORATORY_AGENT_PROMPT.md` | REMOVED FROM ACTIVE TREE | Old UI exploration prompt; preserved in Git history |
| `docs/benchmarks/chronicler-trial.md` | HISTORICAL | Dated benchmark evidence |
| `dev/docs/README.md` | CURRENT REFERENCE | Developer-note index |
| `dev/docs/core/SELF_MODIFICATION_BOUNDARIES.md` | CURRENT REFERENCE | Safety boundaries |
| `dev/docs/reality/persona_compiler.md` | CURRENT REFERENCE | Code-cited persona design rationale |
| `dev/docs/skills/SKILL_TREE.md` | CURRENT REFERENCE | Skill-tree contract |
| `dev/docs/library_review/mochi_demo.md` | HISTORICAL | Animation donor review |
| `dev/docs/roadmap/PERSONA_PIPELINE_ABC_DESIGN.md` | HISTORICAL | Code-cited Mode C design record |
| `dev/docs/roadmap/future_backlog.md` | BACKLOG / DEFERRED | Deferred ideas, not current release scope |
| `jaeger_ai/interfaces/swift/PARITY_PLAN.md` | DELETE FROM ACTIVE TREE | Pre-Gateway bridge-only plan |
| `dev/docs/roadmap/0.9.3_EVERYDAY_AGENCY_PLAN.md` | DELETE FROM ACTIVE TREE | Superseded 0.9.3 sprint |
| `apps/ios/README.md` | HISTORICAL | Donor documentation for the Hermes-branded iOS client |

## Verification snapshot — 2026-09-24

Focused verification run for this cleanup:

```bash
./dev/scripts/run_tests.sh --unit \
  dev/tests/jaeger_ai/core/test_contributor_hardening.py \
  dev/tests/jaeger_ai/core/test_architecture_truth_doc.py \
  dev/tests/jaeger_ai/core/test_test_architecture.py \
  dev/tests/jaeger_ai/core/test_runtime_truth.py \
  dev/tests/jaeger_ai/core/test_control_plane_consolidation.py \
  dev/tests/jaeger_ai/core/test_gateway_admission_snapshot.py \
  dev/tests/jaeger_ai/core/test_request_cancellation.py \
  dev/tests/jaeger_ai/core/test_gateway_tool_events.py \
  dev/tests/jaeger_ai/features/webui/server_regressions/test_one_execution_path.py \
  dev/tests/jaeger_ai/features/webui/server_regressions/test_gateway_mirror.py \
  dev/tests/jaeger_ai/features/webui/server_regressions/test_gateway_stream_admission.py \
  dev/tests/jaeger_ai/core/test_ide_gateway_client.py --tb=short

node --test jaeger_ai/interfaces/ide/tests/*.test.js

swift test --disable-sandbox --scratch-path "$HOME/.cache/jaeger/swift-tests"
```

Results:

- **Python:** 101 passed, 1 deselected, exit 0. A final documentation-focused rerun of the contributor/architecture tests passed 5/5.
- **Gateway live steering:** 7 passed, 0 failed; covers active-agent delivery, `turn.steer` publication, no-agent 409, agent refusal, terminal-request 409, empty-text 400, and wrong-session 404.
- **Gateway product runtime:** 9 passed, 0 failed; covers Gateway-first runtime selection, no-attach isolation, bus-routed approvals, explicit unsupported approvals/steering, request-scoped steering, the explicit bridge diagnostic, and fail-closed ownership when no owner is available.
- **Gateway session queue:** 9 passed, 0 failed; covers schema durability, request identity, edit/pause behavior, queue ordering, idle and busy admission, durable `queue.updated` events, reorder rejection, and terminal-only drain.
- **IDE queue:** 6 Node tests passed, 0 failed; covers the queue REST routes, Gateway-owned follow-up queueing, immediate follow-through when an idle queue item starts, honest no-ReAct-agent 409, edit/reorder/delete, and explicit webview controls with no client-owned steering queue.
- **IDE Plan mode:** 4 Node tests passed, 0 failed; covers `/plan` parsing, the `update_plan`-only admission grant, queued plan work, and the webview/extension contract. The Gateway admission test freezes and replays the same grant.
- **IDE context chips:** 3 Node tests passed, 0 failed; covers `/diagnostics` parsing, bounded problem summaries, and the webview/extension chip projection from the existing IDE context contract.
- **IDE session tabs:** 4 Node tests passed, 0 failed; covers deduplicated open order, close-active/close-other behavior, return to chat home when the last tab closes, and closeable webview tabs.
- **IDE workspace selection:** 3 Node tests passed, 0 failed; covers the real picker control, `/workspace`, per-endpoint persistence, and queued-turn use. The extension suite also proves the selected workspace reaches the Gateway admission body.
- **IDE file mentions:** 2 Node tests passed, 0 failed; covers the real `@` picker and Gateway attachment staging. The extension suite also proves the selected workspace file reaches `addAttachment`.
- **IDE live steering:** 4 Node tests passed, 0 failed; covers the request-scoped route, active-agent steering, the honest no-ReAct-agent 409 without a client queue, and transport-error propagation.
- **IDE Node:** 134 passed, 0 failed, 1 intentional isolated-Gateway fixture skip, exit 0.
  The first run exposed two markdown-helper test failures. `enhanceCodeBlocks` now no-ops
  when its optional DOM query API is absent, and the Node fixture models nested
  `textContent`; the final suite passes.
- **Swift:** 165 executed, 158 passed, 7 skipped, 0 failed, exit 0. Skips are two
  microphone-dependent tests on this no-input host, two process-tree tests whose live
  `ps` snapshot does not expose nested children here, two opt-in Dispatcher live tests,
  and one settings-catalog fixture without an external dump.
- **Markdown links:** 43 active project documents checked; all local links resolve.
  The imported iOS donor README is excluded because it links to files from its upstream
  repository.
- **Whitespace:** `git diff --check` passes.

The first Swift invocation without `--disable-sandbox` was blocked by this host’s
`sandbox-exec` policy (`Operation not permitted`). The test build still used the
documented external scratch path. This is a test-environment note, not a product
capability claim.

No live-provider, physical-device, installed-app, or final-artifact acceptance was run.
