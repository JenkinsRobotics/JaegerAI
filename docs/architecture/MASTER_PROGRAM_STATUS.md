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
| **GATE B** | **WS 7** | **World-State Model** | PENDING | — | — | Entity, Claim, Observation, Provenance model |
| **GATE B** | **WS 8** | **Unified Policy / Capability / Authority** | PENDING | — | — | Policy kernel, deterministic fail-closed authority |
| **GATE B** | **WS 9** | **Typed Effect & Verification Model** | PENDING | — | — | EffectIntent -> EffectLedger -> Verification |
| **GATE C** | **WS 10** | **Programmable Capability Layer** | PENDING | — | — | Dynamic packages/manifests without core edits |
| **GATE C** | **WS 11** | **Capability Lifecycle & Self-Improvement** | PENDING | — | — | Candidate -> Sandbox -> Test -> Gate -> Install |
| **GATE C** | **WS 12** | **Multi-Agent Architecture** | PENDING | — | — | RuntimeHost with isolated EntityRuntime instances |
| **GATE C** | **WS 13** | **Generic Device / Node Architecture** | PENDING | — | — | Device pairing, capabilities, and telemetry |
| **GATE C** | **WS 14** | **Provider Abstraction & Cognition Profiles** | PENDING | — | — | Canonical runtime inventory & cognition profiles |
| **GATE C** | **WS 15** | **Durable Background Work & Scheduling** | PENDING | — | — | Resilient background jobs surviving restart |
| **GATE D** | **WS 16** | **Observability & Provenance Tracing** | PENDING | — | — | End-to-end trace correlation |
| **GATE D** | **WS 17** | **External Agent Evaluation Suite** | PENDING | — | — | Independent benchmark harness (isolated) |
| **GATE D** | **WS 18** | **Fault Injection, Resilience & Soak** | PENDING | — | — | Crash mid-task, reconnect, soak testing |
| **GATE E** | **WS 19** | **Security Hardening** | PENDING | — | — | Threat model, CSRF, passkeys, sandbox traversal |
| **GATE E** | **WS 20** | **Repository Architecture Cleanup** | PENDING | — | — | Invert jaeger-agent dependencies, remove dead code |
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
