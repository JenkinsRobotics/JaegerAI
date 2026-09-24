> **Classification:** HISTORICAL.
> **Superseded by:** [`docs/CONTINUE_FROM_HERE.md`](../../docs/CONTINUE_FROM_HERE.md) (or `../../../docs/CONTINUE_FROM_HERE.md` from `dev/docs`).
> This is dated evidence. It may reference an old branch, HEAD, dirty worktree, or schedule. Do not treat it as current status, implementation order, or release qualification.

# JaegerAI Master Architecture Completion & Public-Release Hardening Program

## Current release direction — 2026-09-23

**Personal companion-assistant RC target: September 28. NOT YET QUALIFIED.**
Authoritative scope, nine acceptance gates, deferrals, five-day schedule and
continuation prompt: [master personal-release plan](GROK_PERSONAL_RELEASE_PROMPT.md#current-release-contract--five-day-revision-2026-09-23).
Current inspected checkout: `next/clean-app`, `917e1eb8`, with extensive uncommitted
work. Preserve staged roadmap and operator Swift changes.

This is a release-scope cut, not a rewrite or a declaration of architectural
convergence. The supported release surfaces are the Gateway owner, existing
WebUI, Antigravity IDE extension, and the macOS menu-bar + Settings control
surface. Native macOS chat, avatar, pill, and other unfinished windows remain
in source but are hidden behind explicit QA opt-in; they are neither removed nor
release gates. Promote useful memory and one contextual proactive workflow.
Product clarification: after RC1–RC3, RC7 also requires one real existing
IDE-worker conversation (task, observed reply, contextual follow-up,
independently verified result) plus visible desktop action feedback and Stop/yield.
The earlier blanket worker deferral was too broad. This adds remaining release
effort without restarting the plan or promising the five-day deadline. Defer
universal worker/provider support, elaborate dashboards, 3D animation, full feature
UI parity, full donor removal and repo-wide restructuring. No capability deletion.

Current code has significant owner/client/settings progress and reusable character
and audio components. The candidate still needs final-artifact/live-provider UI
qualification, physical voice latency/stop proof, proactive delivery and external
Mac packaging. All RC gates remain pending; this documentation pass did not run
application tests. See [current audit](CURRENT_PRODUCT_AUDIT.md).

Reuse the existing IDE panel, Gateway, DelegateRuntime, `ide_orchestration` service,
computer-use skills and browser tools. The orchestration API exists; the default
adapter is CLI-based and its service/task/idempotency/handle records are in-memory.
The bounded service correction now distinguishes completion from verification,
protects terminal cancellation, snapshots concurrent retries, enforces awaited
deadlines and rejects unsupported CLI capabilities/read-only claims. RC7 must
still connect to existing durable owner records and
task-specific verification, and demonstrate control of the actual IDE conversation.
Gateway HTTP now shares the service snapshot contract, forwards all accepted
fields and tracks operations for shutdown. Focused verification: 30 unit tests
and 2 isolated Gateway integration tests passed, both exit 0; no live IDE-worker
or release qualification is claimed. Current built-in CLI adapters reject default
read-only requests because their launchers cannot enforce that mode, and public
writable requests fail closed until server-owned authorization and verification
exist. Public CLI orchestration is therefore intentionally unusable and cannot
satisfy RC7 yet.

[Installed-stack findings and reuse order](GROK_PERSONAL_RELEASE_PROMPT.md#reuse-decisions-for-this-release):
Codex in Antigravity uses OpenAI computer-use runtime/helper components, including
resources bundled in the installed ChatGPT app. Evaluate supported, licensed
reuse of that current stack first. Cua Driver is a fallback candidate, not the
identified current implementation or a finalized dependency. Open Codex App
Server remains a worker lifecycle/protocol reference; selective Cline UI/editor
code is only for an identified gap. In the measured local Ollama comparison,
Cline passed the larger sequence including restart recovery; Kilo v7.7.9 was
selected only as the bounded MIT source donor for frame batching and stable-key
transcript projection. Jaeger's Gateway remains the execution owner; neither
donor runtime is embedded.
Host/model compatibility is unqualified; keep version
and license records in the existing donor ledger. No full extension/runtime fork
or claim that open Codex supplies all the coordinator's computer-control tools.

## Historical program baseline — not current release certification

The tables below retain historical component milestones and reported test counts.
`COMPLETED` in these tables does **not** certify production wiring, today's dirty
source, or the five-day RC. Their branch/baseline describes the old program only.

**Historical branch:** `pinocchio`

**Historical baseline:** `b8c9312b9463545bac135cc839675ab455543bd7`

**Long-term target:** Public Technical Review & Production-Grade Persistent Agent Engine

---

## 1. Architectural Invariants

```text
MODEL != AGENT
SESSION != AGENT
CLIENT != AGENT
DEVICE != AGENT

PROPOSED ACTION != AUTHORIZED ACTION
TOOL SUCCESS != VERIFIED SUCCESS

MEMORY != CONTEXT WINDOW
SUPPORTED != AVAILABLE
AVAILABLE != AUTHORIZED

ONE FACT = ONE AUTHORITATIVE OWNER

ONE REQUEST
    -> ONE EXECUTION PATH
    -> ONE AUTHORITY DECISION
    -> ONE EFFECT RECORD
    -> ONE VERIFICATION CHAIN
```

---

## 2. Program Gates & Workstream Status Matrix

| Gate | Workstream | Description | Status | Commits | Tests Passing | Dependencies / Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **GATE A** | **WS 1** | **WebUI Runtime Truth & Acceptance Suite** | **COMPLETED** | `675fb3e7` | 9/9 acceptance, 6/6 runtime truth, 25/25 proxy | Verified live DOM == SQLite == Provider == Multimodal |
| **GATE A** | **BASE** | **Baseline Evaluation Snapshot** | **COMPLETED** | `97ea1d0a` | 12/12 Pinocchio, 17/17 UPAA, 63/63 Contract | Immutable baseline captured in BASELINE_EVALUATION_SNAPSHOT.md |
| **GATE B** | **WS 2** | **Execution-Model Consolidation** | **COMPLETED** | `33d2ce68` | 7/7 lifecycle, 97/97 jaeger-agent, 9/9 WebUI | Canonical WorkState, durable run 1:1, suspended approval wake keys, crash recovery |
| **GATE B** | **WS 3** | **Control-Plane Consolidation** | **COMPLETED** | `acd7de83` | 4/4 control-plane, 26/26 regression | Gateway reduced to pure control plane; EntityRuntime owns ReAct and execution |
| **GATE B** | **WS 4** | **Typed Contracts & Versioned Schemas** | **COMPLETED** | `df037bbd` | 10/10 schemas, 73/73 contract suite | Pydantic v2 versioned wire & storage schemas for all 18 core entities |
| **GATE B** | **WS 5** | **State-Ownership Consolidation** | **COMPLETED** | `dc5b7158` | 4/4 ownership, 25/25 combined | Single Source of Truth map; strict subsystem persistence boundaries enforced |
| **GATE B** | **WS 6** | **Memory & Context Architecture** | **COMPLETED** | `b1025ff0` | 5/5 compiler, 30/30 combined | Canonical ContextCompiler: SELECT -> RANK -> BUDGET -> PROVENANCE -> FORMAT |
| **GATE B** | **WS 7** | **World-State Model** | **COMPLETED** | `fd1f48d7` | 5/5 world-state, 25/25 combined | Epistemic Invariants (Observation != Claim != Belief != Fact), SqliteWorldStore in knowledge.sqlite3, SemanticMemory integration |
| **GATE B** | **WS 8** | **Unified Policy / Capability / Authority** | **COMPLETED** | `7270cb87` | 7/7 policy kernel, 40/40 combined | Unified PolicyKernel (ALLOW, DENY, MODIFY, REQUIRE_APPROVAL), strict fail-closed, AuthorityLayer integration |
| **GATE B** | **WS 9** | **Typed Effect & Verification Model** | **COMPLETED** | `bdd4f47e` | 5/5 effects, 55/55 Gate B suite | EffectIntent -> EffectLedger -> Execution -> EffectResult -> VerificationResult; connected IDs; disk probes; tool ok != verified |
| **GATE C** | **WS 10** | **Programmable Capability Layer** | **COMPLETED** | `9993b417` | 3/3 capabilities, 58/58 combined | CapabilityManifest (permissions, deps, tools, rollback, verification); CapabilityRegistry; installed, verified & removed without core edits |
| **GATE C** | **WS 11** | **Capability Lifecycle & Self-Improvement** | **COMPLETED** | `3a41bd85` | 4/4 lifecycle, 62/62 combined | Candidate -> Sandbox -> Static AST Checks -> Unit Tests -> Evaluation -> Review -> Verified -> Installed; provenance tracking |
| **GATE C** | **WS 12** | **Multi-Agent Architecture** | **COMPLETED** | `72e2f3c9` | 4/4 multi-agent, 66/66 combined | RuntimeHost (multi-entity concurrent hosting); private memory isolation; scoped delegation; cancellation; AgentMessage bus |
| **GATE C** | **WS 13** | **Generic Device / Node Architecture** | **COMPLETED** | `fac249b3` | 5/5 devices, 71/71 combined | DeviceRegistry (Mac, Web, Phone, Robot, Sensor); secure pairing tokens; revocation; capability negotiation; telemetry & stale detection |
| **GATE C** | **WS 14** | **Provider Abstraction & Cognition Profiles** | **COMPLETED** | `c26cbaf0` | 3/3 cognition profiles, 74/74 combined | 8 Provider Lifecycle States; Cognition Profiles for baseline & discovered models; Model swap identity immutability |
| **GATE C** | **WS 15** | **Durable Background Work & Scheduling** | **COMPLETED** | `651ff0e5` | 4/4 durable tasks, 78/78 combined | SqliteDurableTaskStore; DurableTaskManager; background thread pool; survives client disconnect & restart recovery |
| **GATE D** | **WS 16** | **Observability & Provenance Tracing** | **COMPLETED** | `cd066661` | 5/5 unified trace, 83/83 combined | End-to-end trace correlation (request -> attention -> executive -> context -> cognition -> proposal -> authority -> effect -> verification -> learning); SqliteTraceStore; automatic secret redaction |

| **GATE D** | **WS 17** | **External Agent Evaluation Suite** | **COMPLETED** | `20002f20` | 6/6 eval suite, 89/89 combined | ExternalEvalHarness for BFCL, SWE-bench, Terminal-Bench, and AgentDojo; independent grading; 5-category failure classification; markdown evaluation reporting |


| **GATE D** | **WS 18** | **Fault Injection, Resilience & Soak** | **COMPLETED** | `4bb0e5c4` | 5/5 resilience, 94/94 combined | FaultInjectionEngine (timeout, 500 error, kill mid-effect idempotency, durable task recovery, 5-turn leak-free soak testing) |


| **GATE E** | **WS 19** | **Security Hardening** | **COMPLETED** | `0b68381b` | 6/6 security, 100/100 combined | Formalized THREAT_MODEL.md (6 trust domains); SafeArchiveExtractor (Zip Slip prevention); ToolArgumentSanitizer (command exploit & sandbox traversal checks); CsrfGuard |


| **GATE E** | **WS 20** | **Repository Architecture Cleanup** | **COMPLETED** | `12d05659` | 2/2 boundary purity, 50/50 jaeger-agent, 102/102 combined | Dependency inversion: eliminated upward jaeger_ai imports from jaeger_agent loop; AgentCallbacks telemetry injection; boundary purity enforced via AST inspection |


| **GATE E** | **WS 21** | **Test-Suite Tiering & Determinism** | **COMPLETED** | `b8cbaeda` | 7/7 runner doctrine, 177/177 security, 44/44 production-path, 1/1 soak | `dev/scripts/run_tests.sh` flags are honest; RUN_PACKAGES gates package suites; production-path is kernel contracts not two unit files |
| **GATE F** | **WS 22** | **Documentation Truth Pass** | **COMPLETED** | `ff5ab919` | 1/1 architecture truth doc | Canonical `ARCHITECTURE.md` classifies IMPLEMENTED / EXPERIMENTAL / PLANNED; unit tests are not production proof |
| **GATE F** | **WS 23** | **Developer / Platform API** | **COMPLETED** | `1279edfa` | 6/6 platform API | `jaeger capability validate`, `jaeger provider doctor`, `jaeger device inspect` |
| **GATE F** | **WS 24** | **Clean-Machine Release Validation** | **COMPLETED** | `97a8f5dc` | 3/3 isolated state | Isolated `JAEGER_STATE_DIR` identity + Gateway store; not a wiped macOS VM |
| **GATE F** | **WS 25** | **Public-Release / Contributor Hardening** | **COMPLETED** | `47d454df` | 3/3 contributor files | CONTRIBUTING, extension guide, PR/issue templates |

---

## 3. Physical Acceptance Checklist (Hardware-Only)
- [ ] Passkey / Face ID physical biometrics on iPhone.
- [ ] Actual iOS PWA standalone home-screen launch.
- [ ] Cellular <-> Wi-Fi network handover during an active turn stream.
- [ ] Native iOS system photo picker triggering image turn.

---

## 4. Known Technical Debt & Immediate Dependencies
- Gateway `server.py` still contains historical turn helpers (`_owner_react_turn`, `_sync_model`, `_native_lead_turn`, `_sync_react`). WS-3 added `EntityRuntime.run_subordinate_react` and a control-plane test; residual branches remain until a later deletion pass proves they are unreachable.
- State ownership is documented in `STATE_OWNERSHIP_MAP.md`. Duplicate SQLite files still exist on disk (`gateway_sessions.sqlite3`, `native-turns.sqlite3`, `events.sqlite3`); readers must use the mapped owner, not open a sibling store.
- Workstreams 10–18 added module packages (capabilities, devices, RuntimeHost, eval/fault harnesses) whose unit tests pass. Production Gateway wiring of those packages is **experimental** unless a production-path or acceptance test names them.
- Physical iPhone Face ID / PWA / photo picker remains operator-hardware-only (section 3).
- PolicyKernel owns `pre_tool_call`. `AuthorityLayer` no longer registers `default_shell_hooks_policy` by default (double-fire defect).

---

## 5. Program summary (end of 25 workstreams)

| Item | Value |
| :--- | :--- |
| Starting baseline | `b8c9312b` |
| Branch | `pinocchio` (do not merge to `master`) |
| WS-21 | `b8cbaeda` |
| WS-22 | `ff5ab919` |
| WS-23 | `1279edfa` |
| WS-24 | `97a8f5dc` |
| WS-25 | `47d454df` |
| Architecture | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Tests | [TEST_ARCHITECTURE.md](TEST_ARCHITECTURE.md) |

### Verdict

`JAEGER PLATFORM — NOT READY FOR PUBLIC TECHNICAL REVIEW`

Concrete blockers:

1. Capability registry, RuntimeHost, DeviceRegistry, and the new DurableTaskManager are unit-tested modules. They are not the production Gateway/cron path.
2. Gateway `server.py` still contains residual turn helpers beside `EntityRuntime.execute_turn` / `run_subordinate_react`.
3. External evaluation and fault-injection suites are harnesses. They do not include live published benchmark scores or SIGKILL of the operator Gateway.
4. Clean-machine proof is isolated `JAEGER_STATE_DIR`, not a wiped macOS install with no `~/.jaeger`.
5. Physical iPhone Face ID, PWA home-screen, Wi-Fi↔cellular, and native photo picker are unchecked.
6. Typed contract schemas exist; not every control-plane frame validates on the wire.

Do not treat Gates A–F checkboxes as production proof. Runtime evidence is listed per workstream and in ARCHITECTURE.md.
