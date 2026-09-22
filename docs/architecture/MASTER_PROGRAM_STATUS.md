# JaegerAI Master Architecture Completion & Public-Release Hardening Program

**Branch:** `pinocchio`  
**Starting Baseline Commit:** `b8c9312b9463545bac135cc839675ab455543bd7`  
**Target:** Public Technical Review & Production-Grade Persistent Agent Engine  

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


| **GATE E** | **WS 20** | **Repository Architecture Cleanup** | **COMPLETED** | *pending* | 2/2 boundary purity, 50/50 jaeger-agent, 102/102 combined | Dependency inversion: eliminated upward jaeger_ai imports from jaeger_agent loop; AgentCallbacks telemetry injection; boundary purity enforced via AST inspection |

| **GATE E** | **WS 21** | **Test-Suite Tiering & Determinism** | PENDING | — | — | Tiered test commands (unit, integration, soak, etc.) |
| **GATE F** | **WS 22** | **Documentation Truth Pass** | PENDING | — | **Implemented/Experimental/Planned/Deprecated** | Clean spec |
| **GATE F** | **WS 23** | **Developer / Platform API** | PENDING | — | — | Public CLI commands & extension contracts |
| **GATE F** | **WS 24** | **Clean-Machine Release Validation** | PENDING | — | — | Zero-dependency clean environment install |
| **GATE F** | **WS 25** | **Public-Release / Contributor Hardening** | PENDING | — | — | Contributor guide, license audit, release readiness |

---

## 3. Physical Acceptance Checklist (Hardware-Only)
- [ ] Passkey / Face ID physical biometrics on iPhone.
- [ ] Actual iOS PWA standalone home-screen launch.
- [ ] Cellular <-> Wi-Fi network handover during an active turn stream.
- [ ] Native iOS system photo picker triggering image turn.

---

## 4. Known Technical Debt & Immediate Dependencies
- Live Gateway OWNER in-process turn execution (`server.py`) has multiple branching pathways (`_owner_react_turn`, `_sync_model`, `_native_lead_turn`, `_sync_react`) which will be consolidated in Workstream 2 and Workstream 3 into `EntityRuntime.execute_turn`.
- State stores: `gateway_sessions.sqlite3`, `native-turns.sqlite3`, `events.sqlite3` will be strictly owned and mediated as mapped in Workstream 5.
