# ARCHITECTURE_AFTER.md — Pinocchio Persistent Entity Runtime Architecture

**Document Version:** 1.1.0 (Pinocchio Architecture Semantic Audit Release)  
**Author:** Principal Systems Architect  
**Status:** Canonical Production Architecture  
**Audit Standard:** [Universal Persistent Agent Architecture (UPAA)](UNIVERSAL_PERSISTENT_AGENT_ARCHITECTURE.md)

---

## 1. Executive Summary: The Consolidated Entity

The Pinocchio architecture establishes a single, authoritative **Persistent Entity Runtime** for JaegerAI, implementing the [Universal Persistent Agent Architecture](UNIVERSAL_PERSISTENT_AGENT_ARCHITECTURE.md) baseline.

### The Foundational Invariants
* **MODEL ≠ AGENT:** The Large Language Model is not Jaeger. Models (Hermes, Claude, OpenAI, Gemini, Ollama) are replaceable cognition engines invoked on demand.
* **PERSONA ≠ IDENTITY:** Persona modulates expressive style, tone, and character. Identity is the persistent, immutable anchor surviving across sessions, hosts, and model swaps.
* **SESSION ≠ IDENTITY:** Sessions and conversations belong to the entity; the entity never belongs to a session.
* **AUTHORITY ORDERING:** `COGNITION PROPOSES ACTION → AUTHORITY LAYER → ACTION SYSTEM/EXECUTOR → ENVIRONMENT`. An executor never gets an unapproved action.
* **VERIFICATION ≠ EFFECT LEDGER:** `TOOL RETURN SUCCESS ≠ OBJECTIVE VERIFIED`. EffectLedger accounts for execution idempotency; VerificationContract inspects independent real-world ground truth.
* **HEARTBEAT IS A TRIGGER ONLY:** Heartbeat triggers sleep-time cycles; `SleepTimeProcessor` owns consolidation, reflection, and indexing semantics.
* **SINGLE RUNTIME AUTHORITY:** All ingress paths (CLI, Bridge, Gateway, Heartbeat, Background, Passive/Salient Sensors) execute against the identical `EntityRuntime` singleton instance.

```
                         JAEGER ENTITY RUNTIME
                            (EntityIdentity)
                                   │
                                   ▼
                         SQLITE EVENT STORE
                         (entity_events.sqlite3)
                                   │
                                   ▼
                         DETERMINISTIC REDUCER
                                   │
                                   ▼
                               SELF STATE
             ┌─────────────────────┼─────────────────────┐
             ▼                     ▼                     ▼
        World Model           Active Goals          Commitments
     (Entities/Claims)
             │                     │                     │
             └─────────────────────┼─────────────────────┘
                                   │
                                   ▼
                            SALIENCE ENGINE
                     (Passive vs Cognition Wake)
                                   │
            ┌──────────────────────┴──────────────────────┐
            ▼                                             ▼
 [Salience < Threshold]                        [Salience >= Threshold]
      Silent Record                                EXECUTIVE
     (0 Model Calls)                       (Strategy Selection)
                                                          │
                                                          ▼
                                                   COGNITION MODES
                                               (ReAct, Planning, etc.)
                                                          │
                                                          ▼
                                                   PROPOSED ACTION
                                                          │
                                                          ▼
                                                   AUTHORITY LAYER
                                                (Policy Kernel, Veto)
                                                          │
                                                          ▼
                                                    ACTION SYSTEM
                                                (EffectLedger, Tools)
                                                          │
                                                          ▼
                                                     ENVIRONMENT
                                                          │
                                                          ▼
                                                  CONSEQUENCE EVENT
                                                          │
                                                          ▼
                                                VERIFICATION CONTRACT
                                         (Tool Success ≠ Objective Verified)
                                                          │
                                                          ▼
                                                  LEARNING PIPELINE
                                            ┌─────────────┼─────────────┐
                                            ▼             ▼             ▼
                                         Memory         World        Skills
                                                          │
                                                          ▼
                                                SLEEP-TIME PROCESSING
                                              (Triggered by Heartbeat)
```

---

## 2. Core Subsystems in `jaeger_ai/core/entity/`

### 1. `EntityIdentity` (`identity.py`)
- Persistent identity record anchored at `<state_root>/entity_identity.json`.
- Holds unique `entity_id` (`jaeger-entity-...`), display name, creation timestamp, and system purpose.
- Fully decoupled from character sheets, persona presets, and operator identity.

### 2. `JaegerEvent` (`events.py`) & `SqliteEventStore` (`event_store.py`)
- Normalized event contract standardizing all occurrences with monotonic IDs and causal provenance.
- Persistent append-only event log stored in `<state_root>/entity_events.sqlite3` (WAL mode, busy timeout, foreign keys, indexed queries).
- Complete chronological replay support for cold boot state reconstruction.

### 3. `SelfState` (`self_state.py`) & `reduce_event` (`reducer.py`)
- Authoritative compact projection of the entity's current reality (identity, active goals, commitments, telemetry, recent insights).
- Pure deterministic reducer `(SelfState, JaegerEvent) -> SelfState` enabling zero-loss cold boot replay.

### 4. `SalienceEngine` (`attention.py`)
- Evaluates whether an incoming event warrants invoking cognition.
- Separates routine telemetry and passive heartbeats (salience < 0.3, 0 LLM calls) from urgent alerts, human direct messages, and scheduled briefings (salience >= 0.7, cognition awakened).

### 5. `AuthorityLayer` (`authority.py`)
- Enforces strict canonical authority ordering: `PROPOSED ACTION → AUTHORITY LAYER → ACTION SYSTEM → ENVIRONMENT`.
- Evaluates `ProposedAction` through deterministic security policies and shell veto hooks (`pre_tool_call`). No executor executes an action without prior authorization.

### 6. `VerificationContract` (`verification.py`)
- Separates:
  1. Execution Attempted (`VerificationStatus.ATTEMPTED`)
  2. Tool Returned Success (`VerificationStatus.TOOL_SUCCESS`)
  3. Effect Recorded (`VerificationStatus.EFFECT_RECORDED`)
  4. Intended Objective Actually Verified (`VerificationStatus.OBJECTIVE_VERIFIED`)
- A tool return of `ok=True` without an independent external verifier produces `OBJECTIVE_UNVERIFIED`. `verify_disk_state()` independently validates real filesystem outcomes.

### 7. `MemorySubsystem` (`memory.py`)
Explicitly owns the 5 canonical memory classes:
1. **Working Memory:** In-memory scratchpad and active goals (`WorkingMemory`).
2. **Episodic Memory:** Chronological immutable event log (`EpisodicMemory`, `SqliteEventStore`).
3. **Semantic Memory:** Structured entity/claim relational tables (`SemanticMemory`, `<state_root>/knowledge.sqlite3`).
4. **Reflective Memory:** Distilled meta-cognitive lessons (`ReflectiveMemory`, `<state_root>/reflective_insights.json`).
5. **Procedural Memory:** Verified skills and recipes (`ProceduralMemory`, `<state_root>/skills/`).
*Architectural Boundary Note:* `SessionStore` (`jaeger_ai/core/gateway/session_store.py`) is strictly a transport-level SSE/REST client session cache, NOT the entity's memory system.

### 8. `ExecutiveStrategySelector` (`executive.py`)
Deterministically selects among 6 cognitive strategies:
- `PASSIVE_OBSERVE` (salience < 0.3, 0 LLM calls)
- `DIRECT_RESPONSE` (conversational/informational prompt)
- `REACT_LOOP` (action verbs, tool loop with consequence feedback)
- `DELIBERATE_PLANNING` (batch work, /goal command, work ledger)
- `SPECIALIST_DELEGATION` (routing to specialist model/agent e.g. Codex)
- `SLEEP_TIME_CONSOLIDATION` (offline reflection triggered by idle/quiet heartbeat)

### 9. `SleepTimeProcessor` (`sleep_time.py`)
- Decouples heartbeat triggers from consolidation semantics.
- Scheduler/heartbeat acts as a **trigger only**.
- Coordinates consolidation (episodic -> semantic claims), reflective synthesis (error analysis -> insights), and skill review.
- Emits low-salience `memory.consolidated` events into the Event Fabric.

### 10. `LearningPipeline` (`learning.py`)
- Converts verified real-world experience into durable cross-session updates across:
  - Episodic memory (durable event log)
  - Semantic knowledge / World model (verified claims)
  - Reflective memory (lessons generated from failed objectives)
  - Skill library (promoted candidate procedures)
  - Strategy metadata (reinforced or penalized tool confidence)

### 11. `EntityRuntime` (`runtime.py`)
- The single process-wide runtime coordinator unifying all ingress interfaces (CLI, Bridge, Gateway, Heartbeat, Background tasks, Passive/Salient Sensors).
- Implements the complete UPAA canonical loop.

---

## 3. Verification & Compliance Evidence

All subsystems are validated by comprehensive automated test suites:
- `dev/tests/test_runtime_trace.py`: Verifies authority ordering, verification distinction, memory taxonomy, executive strategy selection, sleep-time processing, learning pipeline, and single runtime authority trace (100% pass).
- `dev/tests/test_pinocchio_entity.py`: Verifies acceptance criteria A through L (100% pass).
- Monorepo package suites: 913 tests passing in `packages/jaeger-agent`, 283 tests passing in `packages/jaeger-os` (1,215 total tests passing).
