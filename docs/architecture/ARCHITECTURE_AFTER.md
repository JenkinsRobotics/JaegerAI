# ARCHITECTURE_AFTER.md — Pinocchio Persistent Entity Runtime Architecture

**Document Version:** 1.0.0 (Pinocchio Architecture Release)  
**Author:** Principal Systems Architect  
**Status:** Canonical Production Architecture  

---

## 1. Executive Summary: The Consolidated Entity

The Pinocchio architecture establishes a single, authoritative **Persistent Entity Runtime** for JaegerAI.

### The Foundational Invariants
* **MODEL ≠ AGENT:** The Large Language Model is not Jaeger. Models (Hermes, Claude, OpenAI, Gemini, Ollama) are replaceable cognition engines invoked on demand.
* **PERSONA ≠ IDENTITY:** Persona modulates expressive style, tone, and character. Identity is the persistent, immutable anchor surviving across sessions, hosts, and model swaps.
* **SESSION ≠ IDENTITY:** Sessions and conversations belong to the entity; the entity never belongs to a session.

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
      Silent Record                                   Cognition
     (0 Model Calls)                                      │
                                                          ▼
                                                        Action
                                                          │
                                                          ▼
                                                 Tool Consequence Event
                                                          │
                                                          ▼
                                                  Memory & Learning
```

---

## 2. Core Subsystems in `jaeger_ai/core/entity/`

### 1. `EntityIdentity` (`identity.py`)
- Persistent identity record anchored at `<state_root>/entity_identity.json`.
- Holds unique `entity_id` (`jaeger-entity-...`), display name, creation timestamp, and system purpose.
- Fully decoupled from character sheets, persona presets, and operator identity.

### 2. `JaegerEvent` (`events.py`)
- Normalized event contract standardizing all occurrences:
  - `human.message`, `system.heartbeat`, `system.observation`, `tool.started`, `tool.completed`, `tool.failed`
  - `goal.created`, `goal.completed`, `commitment.created`, `commitment.updated`
  - `agent.action`, `agent.response`, `memory.consolidated`, `background.completed`
  - `perception.sensed`, `skill.candidate`, `skill.promoted`
- Structured metadata: `event_id`, `actor`, `source`, `timestamp`, `session_id`, `salience`, `idempotency_key`, `payload`, `provenance`.

### 3. `SqliteEventStore` (`event_store.py`)
- Persistent append-only event log stored in `<state_root>/entity_events.sqlite3`.
- WAL mode, busy timeout, foreign keys, index-backed time and session queries.
- Complete chronological replay support for cold boot state reconstruction.

### 4. `SelfState` (`self_state.py`)
- Authoritative compact projection of the entity's current reality:
  - Identity, boot time, last event timestamp, last user interaction timestamp.
  - Active interfaces (`gateway`, `bridge`, `cli`), active sensors (`desktop_activity`).
  - Current activity, current focus, active goals, commitments, important people, uncertainty areas, resource telemetry, recent insights.
- **Truthful continuity invariant:** Strictly grounded in demonstrable runtime facts; zero fake consciousness assertions.

### 5. `reduce_event` (`reducer.py`)
- Pure deterministic state reducer `(SelfState, JaegerEvent) -> SelfState`.
- Reconstructs exact `SelfState` from stored events without reliance on volatile memory.

### 6. `SalienceEngine` (`attention.py`)
- Evaluates whether an incoming event warrants invoking cognition.
- Separates routine telemetry and passive heartbeats (salience < 0.7, 0 LLM calls) from urgent alerts, human direct messages, and scheduled briefings (salience >= 0.7, cognition awakened).

### 7. `EntityRuntime` (`runtime.py`)
- The single process-wide coordinator implementing the canonical loop:
  `EVENT -> PERSIST -> UPDATE SELF/WORLD STATE -> ATTENTION/SALIENCE -> COGNITION IF REQUIRED -> ACTION -> OBSERVE CONSEQUENCE -> EVENT -> MEMORY/LEARNING`.

---

## 3. Integrated Capabilities

* **Truthful Heartbeat (`heartbeat.py`):**
  Standing checks emit `system.heartbeat` events. When quiet, state updates and returns `HEARTBEAT_OK` with ZERO LLM calls. Briefings and urgent cards wake cognition with system event provenance.
* **Tool Consequence Loop (`tool_executor.py`):**
  Every tool dispatch records `tool.started` and `tool.completed`/`tool.failed` with timing, parameters, and results, updating the entity's uncertainty areas and world model.
* **Memory Consolidation / Dreaming (`consolidation.py`):**
  Offline/idle reflection processes episodic events, extracting claims and relations into `WorldModel` (`packages/jaeger-agent/.../world.py`) and recording consolidated insights.
* **Proactive Sensing (`sensors/`):**
  SensorAdapter contract monitors user idle time, foreground app metadata, and disk telemetry without invasive spyware.
* **Voyager Skill Promotion (`skills/promotion.py`):**
  Extracts candidate skills from successful executions, subjects them to automated verification assertions, and promotes passing skills into the persistent skill library.
* **Unified Ingress:**
  Gateway (`server.py`), Bridge (`bridge.py`), and CLI (`main.py`) all submit events into `EntityRuntime`.
