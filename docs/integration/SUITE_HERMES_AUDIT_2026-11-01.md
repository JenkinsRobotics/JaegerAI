# Jenkins Robotics suite audit and Hermes alternative

Snapshot: 2026-11-01. Scope: every immediate directory in `/Users/matthewjenkins/GitHub` (including existing Jaeger worktrees and build containers), plus the newly cloned official Hermes Agent.

## Evidence and limits

This is a repository inventory and source-contract audit, with deeper inspection of the agent, terminal, voice, device and engineering integration boundaries. Every listed repository was inventoried, root metadata/license/README sampled, and tracked source or engineering assets classified. It is not a claim that every line was reviewed, every test ran, hardware was exercised, or any application is production-ready. Counts include vendored/reference/test material; test file counts are not test passes. Dirty flags include existing changes and untracked material. No pre-existing changes were removed.

Raw evidence: `repo-inventory.json`, `source-samples.json`, `source-contracts.json` beside this report in `~/.cache/jaeger/verification/suite-audit-20261101/`. Git commits below pin observations. Main JaegerAI advanced from e84a5e56 to 2af16e57 during inventory through another actor's IDE merge; current work is isolated at `JaegerAI-worktrees/hermes-suite-20261101`, branch `audit/hermes-suite-20261101`.

Hermes: cloned https://github.com/NousResearch/hermes-agent into `~/GitHub/hermes-agent`, shallow source checkout at c7da41dd522dc19cc08bbfcfa69d4b078224b45d. No installer or runtime started. MIT license verified in local LICENSE. The existing hermes-webui folder is a separate JenkinsRobotics fork, not the agent.

## Product and ownership decisions

JaegerAI is the functional assistant alternative. Keep one Gateway, one task/effect owner, one identity/memory authority. Reuse packages for cognition and speech; integrate independent engineering/device apps through explicit contracts. A donor is a bounded licensed change with its tests and source commit, not a reason to paste in an entire second runtime.

## All local repositories and containers

| Folder | Commit | Tracked / source / test files | Role | Audit disposition |
|---|---|---:|---|---|
| AdamsSimulation | b8a17a11 | 42 / 0 / 0 | Engineering corpus | STEP/mechanism/simulation assets; use as bounded read/import fixtures, not executable agent code. |
| Aether-Animation | 56601873 | 40 / 1 / 0 | Scaffold, not implementation | Tracked README and {{package_name}}/__init__.py still contain template placeholders; 40 tracked files, 1 Python scaffold. Real CAD/animation code is under AetherStudio. |
| Aether-CAD | 6196372c | 40 / 1 / 0 | Scaffold, not implementation | Tracked README and {{package_name}}/__init__.py still contain template placeholders; 40 tracked files, 1 Python scaffold. Real CAD/animation code is under AetherStudio. |
| Aether-IO | 224782ca | 40 / 1 / 0 | Scaffold, not implementation | Tracked README and {{package_name}}/__init__.py still contain template placeholders; 40 tracked files, 1 Python scaffold. Real CAD/animation code is under AetherStudio. |
| Aether-Map | 0a1821ce | 40 / 1 / 0 | Scaffold, not implementation | Tracked README and {{package_name}}/__init__.py still contain template placeholders; 40 tracked files, 1 Python scaffold. Real CAD/animation code is under AetherStudio. |
| Aether-Sketch | a473aed8 | 40 / 1 / 0 | Scaffold, not implementation | Tracked README and {{package_name}}/__init__.py still contain template placeholders; 40 tracked files, 1 Python scaffold. Real CAD/animation code is under AetherStudio. |
| Aether-Vector | 6e46c94c | 40 / 1 / 0 | Scaffold, not implementation | Tracked README and {{package_name}}/__init__.py still contain template placeholders; 40 tracked files, 1 Python scaffold. Real CAD/animation code is under AetherStudio. |
| AetherStudio | ece02091 | 3505 / 1324 / 417 | Separate suite application | Integrate its CAD engine, animation authoring and host through supported services; core/ui is a design donor. CAD launcher hardcodes 8790, colliding with Jaeger WebUI. |
| affinity-circuit-symbols-asset | cdb68f02 | 23 / 0 / 0 | Asset donor | Circuit symbols for engineering documents; MIT attribution belongs to original Keisuke source as well as fork history. |
| Arduino-LD19 | cd4ff6dd | 15 / 8 / 0 | Hardware donor via JROS | Packet-parsing Arduino examples; adapt into a JROS sensor node and replay captured packets before hardware. |
| Arduino-STServo | 01a1b075 | 224 / 190 / 0 | Hardware donor via JROS | Servo examples/drivers include upstream libraries; preserve component licenses and device bounds; do not expose raw motor writes to a model. |
| Autonomous_Rover | bcde3987 | 10 / 0 / 0 | Project corpus | No tracked source in the inspected source extensions; knowledge/project input, not a ready motion stack. |
| Duet2CNC | ef3cfafc | 241 / 0 / 0 | Machine integration corpus | G-code/macros/configuration; simulation and operator-approved jobs through JROS, not unconstrained terminal execution. |
| GradSchool-ESP32 | 9f1052db | 467 / 195 / 17 | Reference examples | Large reference/tutorial tree mixed with firmware; extract narrowly owned sensor/device examples with provenance. |
| hermes-agent | c7da41dd | 21963 / 15900 / 9792 | External functional benchmark / selective donor | Official NousResearch clone; study terminal/session continuity, clarification UI, skills, memory and durable cron outcomes. MIT, retain notices for any reused code. Do not embed a second execution owner. |
| hermes-webui | a333cc87 | 1835 / 1495 / 1398 | Existing reference / donor | JenkinsRobotics fork on jaeger-adapter; compare authenticated proxy, workspace and streaming behavior. Keep current shared React UI and Gateway authority. |
| jaeger-agent | 4e086e63 | 1724 / 516 / 101 | Core package | Standalone reusable loop/tools/skills/memory. 384 identical Python files, 36 different versus current monorepo; select a publishing/sync authority before backporting. |
| jaeger-chat | 09105052 | 413 / 97 / 7 | Client/UI donor | VS Code-derived UI with Microsoft MIT notice; preserve notices. Keep client role, never add an independent agent loop here. |
| jaeger-chat-build | not a repo | 0 / 0 / 0 | Build folder | No Git repository/registered tracked files at this root; not a standalone product donor. |
| JaegerAI | 2af16e57 | 5323 / 2911 / 1196 | Primary product | One identity, Gateway, task owner, persistent state; prioritize complete terminal workflows then the same contract in browser and Mac. |
| JaegerAI-appcontrol | 5217913a | 5199 / 2806 / 1133 | Worktree, not separate product | feat/app-control; dirty at audit time. Review branch deltas rather than copy files or merge implicitly. |
| JaegerAI-backlog-reconcile | 4485c690 | 5222 / 2826 / 1140 | Worktree, not separate product | feat/backlog-reconcile; review provenance and acceptance evidence per change before integrating. |
| JaegerAI-j069 | 2559b21f | 5224 / 2828 / 1141 | Worktree, not separate product | feat/j069-gateway-read-workspace; inspect read/workspace grants, never assume whole branch is in master. |
| JaegerAI-worktrees | not a repo | 0 / 0 / 0 | Worktree container | Enumerate child checkouts separately; this root itself has no tracked source. New audit worktree lives here. |
| JaegerKokoroTTS | 2dbc9342 | 17 / 10 / 2 | Speech engine package | Synthesizer/node/persistent playback; preserve engine contract and cancellation. Standalone nested node layout differs from monorepo layout; raw directory copy is incorrect. |
| JaegerWhisperSTT | 3a95d53c | 27 / 20 / 2 | Speech engine package | Continuous/two-pass/local-agreement transcription; use committed transcripts/events and existing node interface. Nested layout differs from monorepo. |
| Jenkins3D | 3b8b6785 | 344 / 0 / 0 | Machine/project corpus | Printer CAD, configurations and G-code; useful for file search/import/analysis journeys, not core assistant runtime. |
| JenkinsCNC | 5e6c6a8c | 391 / 0 / 0 | Machine/project corpus | CNC configuration, macros and drawings. Integrate proposed jobs with artifact verification and explicit operator approval. |
| JenkinsCNCPostProcessor | 75fb003f | 70 / 0 / 0 | Manufacturing donor | Postprocessor/macros; verify exact controller dialect against sample outputs. Keep process-specific behavior outside agent brain. |
| JenkinsRobotics.github.io | 2a622e8c | 58 / 0 / 0 | Distribution/brand site | Static site and styling; future release docs/download links after actual artifact qualification. |
| JenkinsSLA | 9e3a82e0 | 10 / 0 / 0 | Engineering corpus | Documents/design input; no tracked general-purpose source in inspected extensions. No claim of software runtime. |
| JP01_Firmware | ca660f3a | 1295 / 644 / 109 | Separate robot application | controllers/JP01-CC01/core/capability.py and safety.py expose bounded capability dispatch and EStopLatch. Reuse through JROS contract; Python latch is not hard-real-time safety. |
| JROS | b47c0cde | 1774 / 800 / 277 | Device operating framework | Transport/topics/node lifecycle/body contract. Hardware e-stop and admission remain below the assistant. 418 standalone Python paths absent in monorepo comparison reflect extraction/history, not 418 missing features. |
| Lilith-AI | 4d2d1fbc | 450 / 250 / 63 | Historical donor only | Archive tree and benchmark/persona material; trace forward to current JROS/Jaeger implementation before restoring anything. |
| SCServo_JR | c92fb30b | 410 / 79 / 0 | Hardware driver donor | C++ servo library includes tracked build outputs; isolate source/protocol and test packets. No broad application copy. |
| Servo-Driver-with-ESP32 | ac24be32 | 22 / 17 / 0 | Hardware driver donor | SCServo implementation for ESP32; adapt below JROS permissions and limits, review upstream license headers. |
| starshiprocket | ecfb5f7f | 130 / 11 / 0 | Project corpus / hardware reference | Mechanical assets and load-cell examples; offline simulation and analysis only during assistant qualification. |
| template-design-project | 11a2352a | 8 / 0 / 0 | Project template | Document/project structure; read as planning scaffolding rather than evidence of completed CNC features copied into README. |
| template-engineering-complex | ccc8007b | 15 / 0 / 0 | Project template | Engineering lifecycle documents; README still contains Jenkins CNC project-specific text. Parameterize before reuse. |
| template-engineering-simple | 72d859fe | 22 / 0 / 0 | Project template | Engineering scaffold with inherited machine-project claims; no executable assistant dependency. |
| template-software-application | 35647579 | 47 / 31 / 4 | Chassis reference | Supervised worker/device-sim examples and smoke tests; app-format design donor, not an alternative owner inside JaegerAI. |
| TicTacToe_UR_Robot | 588835cb | 10 / 0 / 0 | Robot project corpus | README repeats Jenkins CNC description; actual tracked assets must drive integration assessment, not the README title/claims. |
| VoiceLLM | 8942d80c | 72 / 49 / 4 | Voice design donor | agent/orchestrator.py: self-speech rejection, speech gating, follow-up window and pending voice handling. Adapt into current speech/runtime contracts; do not transplant its separate LLM owner. |

## Findings that change the implementation order

1. **TUI cannot answer Gateway clarification forms**: `jaeger_ai/interfaces/tui/app.py::_execute_client_turn` handles approval.request but not clarify.request; GatewayTurnClient has no answer method. Hermes `tools/clarify_tool.py:115` injects a platform callback and distinguishes outcomes. Implement Jaeger's existing revisioned form contract on the terminal input lane; Stop must cancel, never fabricate an answer. No Hermes code copied for this fix.
2. **Aether CAD / Jaeger WebUI port collision**: `AetherStudio/Aether CAD/Launcher/AetherCADApplication.swift:7` fixes enginePort=8790. Jaeger uses 8790 too. Resolve address ownership/configurable endpoints before claiming concurrent suite operation. Aether Studio root host defaults to 8780; distinguish host from CAD app port.
3. **Repository names overstate implementations**: six Aether component repos retain {{REPO_NAME}} / {{package_name}} templates. Do not schedule their nonexistent engines as dependencies; use real AetherStudio paths. `aether-dynamics/` currently contains a README scaffold.
4. **Split source ownership**: direct byte comparison found jaeger-agent 384 identical / 36 changed Python files between standalone and JaegerAI package. JROS and speech trees have historical/layout divergence. Compare contracts/tests per component rather than synchronizing blindly.
5. **Public licenses are mixed at component level**: root Apache files do not erase upstream MIT notices in jaeger-chat, Hermes, servo or symbol donor material. Preserve source paths, commit IDs, copyright and license text for reused code.
6. **Working checkout != served build**: record Git revision, UI build digest and installed process cwd separately. Current worktree/branch fragments must not silently replace the running application.

## Concrete Hermes comparison and acceptance journeys

Source inspected in Hermes: `tools/clarify_tool.py`, `tools/skills_tool.py`, `agent/memory_manager.py`, `tools/terminal_tool.py`, `cron/scheduler_tick.py`; AST definition/import inventory saved in source-contracts.json. These establish implementation candidates, not executed Hermes benchmark results.

| Workflow | Hermes source reference | Jaeger authority / path | Acceptance proof needed |
|---|---|---|---|
| Setup and provider selection | hermes_cli/model_setup.py, onboarding_run.py | existing Jaeger config/provider catalog | clean scratch install, choose configured provider, truthful model identity |
| Chat, restart and session recall | hermes_cli/gateway_client.py and agent/session* | GatewaySessionStore + GatewayTurnClient | one session, multi-turn, restart, continue same history |
| Tool use, terminal and cancellation | tools/terminal_tool.py and lifecycle/backends helpers | jaeger-agent tools + Jaeger authority/effect ledger | approved file effect, denial with no effect, Stop and next turn |
| Clarification | tools/clarify_tool.py callback | revisioned Gateway forms + TUI | question, free text/choice, exact revision answer, cancellation, no second turn |
| Memory | agent/memory_manager.py | existing Jaeger attributed memory | remember/recall/correct/forget across restart without a second memory authority |
| Skills | tools/skills_tool.py catalog/readiness | jaeger-agent skill catalog/executor | discover, load, validate, apply a stored skill and inspect effect |
| Background work | cron/scheduler_tick.py / delivery outcomes | Jaeger task owner, scheduler, outbox | scheduled job survives restart; outcome and delivery receipts; no replay |
| Devices / engineering | Jenkins repos, not Hermes parity | JROS + independent Aether apps | capability discovery, exact artifact approval, simulation, refusal when unavailable |

## Priorities and effort

Effort classes indicate scope, not promised completion dates. Priority score = (impact + risk) * (6 - effort), each 1-5.

| Priority | Work | Impact/risk/effort | Score | Done means |
|---|---|---|---:|---|
| P0 | Complete TUI question/answer/Stop through existing Gateway | 5/4/2 | 36 | focused tests + owned Gateway journey |
| P0 | Establish baseline and preserve process/build provenance | 5/4/2 | 36 | full exit codes/logs, recorded blockers, no assumed green |
| P1 | TUI recovery/reconcile and provider setup journey | 5/4/3 | 27 | interrupted request reconciled without duplicate execution |
| P1 | Memory, skills, schedule restart qualification | 5/5/4 | 20 | real effects and restart evidence, not source inventory |
| P1 | Align standalone/package release authority | 4/4/3 | 24 | one authoritative source per shared package plus versioned dependency tests |
| P2 | Resolve port collision and add suite capability discovery | 4/4/3 | 24 | Jaeger and Aether coexist and report truthful health |
| P2 | Voice donor adaptation using current engines | 4/3/4 | 14 | mic/speaker test with stop/self-speech rejection |
| P3 | Physical integrations via JROS | 3/5/5 | 8 | simulation and bounded approved hardware contract |

## Implementation status

Started on the isolated branch: GatewayTurnClient.answer_clarify, TUI clarify.request rendering/answer dispatch, choice-number/free-text input, blank-answer refusal and Stop cancellation. It reuses existing Jaeger Gateway form ownership rather than copying Hermes runtime. Focused tests cover no duplicate turn, choice mapping, blank input, cancellation and encoded session/form identifiers. Verification results are recorded separately once complete.

Next depth: TUI unknown-outcome recovery/reconcile, a scratch-provider end-to-end terminal session, then memory/skills/background jobs. WebUI/Mac must run the same contracts before release. Broad UI redesign and IDE work do not gate this first terminal milestone.

## Verification evidence, 2026-11-01

- Focused TUI/Gateway/auth/form suite: **79 assertions passed**, including an actual HTTP form answer and foreign-session/stale/duplicate refusal. Process exit was **1**, because the repository-wide live-state fingerprint guard observed changes to Ares/Hermes/Muse worker state and jobs/runner.json during the run. This is not a clean green suite; attribution of those live-file changes is unresolved. The patch's tests use scratch state and owned listeners. No guard was disabled and no production worker was stopped.
- Direct owned Gateway journey: **exit 0**, `tui-gateway-journey.json`. Real terminal turn method -> REST/SSE -> real Gateway/agent/tool -> original form answer -> completed assistant reply. Model transport and user input were scripted. Exactly one user message persisted; no duplicate turn. This does not prove physical terminal keystrokes or a live model provider.
- Baseline main-checkout verify.sh: exit 1; two hygiene assertions found existing root __pycache__. Isolated worktree verify.sh: 9 hygiene assertions passed, then the same live-state fingerprint guard returned exit 1, so downstream pipeline stages did not run.
- `git diff --check`: passed. Main checkout continued advancing independently (03094d0c observed); new code remains on audit/hermes-suite-20261101 based at 2af16e57, unmerged and undeployed.
- Additional owned Gateway answer/Stop regression tests are in dev/tests/jaeger_ai/interfaces/test_tui_gateway_clarify.py; results recorded in tui-owned-gateway-tests.log.

SCServo_JR has no root/one-level license file in the inventory: resolve source ownership/license before extracting any driver code. Presence in JenkinsRobotics does not establish the license of imported library components.

Final owned Gateway regression result: **2 passed in 45.05 seconds** (answer and Stop). Its final process exit was 1 because the live-state fingerprint guard again observed changes to running worker/job files. Together with 79 focused passes and the independent exit-0 journey, functional behavior is demonstrated; repository-wide isolation qualification remains open. No tests or live-state guards were skipped.

Review patch is saved at `~/.cache/jaeger/verification/suite-audit-20261101/tui-clarification-and-suite-audit.patch`; the authoritative edits remain in the isolated worktree. No source from Hermes was copied in this patch. The audit identifies further donor candidates rather than asserting they are integrated.
