# Universal Persistent Agent Architecture (UPAA)

**Status:** Canonical Architectural Standard for JaegerAI  
**Baseline Date:** 2026-09-20  
**Authority:** Architectural Baseline Document  

---

## 1. Top-Level Definition

* The **Agent** is the persistent system.
* The LLM is a replaceable **Cognition Provider** used by the Agent.

The Agent consists of:
1. Agent Identity
2. Event Fabric
3. Perception Layer
4. Attention / Salience Layer
5. Self State
6. World Model
7. Memory System
8. Executive / Planner
9. Cognition Layer
10. Cognition Providers
11. Action / Tool System
12. Policy / Authority Boundary
13. Verification Layer
14. Learning Layer
15. Skill Library
16. Sleep-Time Processing
17. Multi-Agent / Cognitive Subagents

### Canonical Execution Loop
$$\text{EVENT} \longrightarrow \text{PERSIST} \longrightarrow \text{PERCEIVE / REDUCE} \longrightarrow \text{UPDATE SELF + WORLD} \longrightarrow \text{ATTENTION / SALIENCE} \longrightarrow \text{EXECUTIVE DECISION} \longrightarrow \text{COGNITION IF REQUIRED} \longrightarrow \text{ACTION} \longrightarrow \text{OBSERVE CONSEQUENCE} \longrightarrow \text{VERIFY} \longrightarrow \text{LEARN} \longrightarrow \text{NEW EVENT}$$

The loop continues over the lifetime of the Agent across process restarts, model swaps, and UI surfaces.

---

## 2. Fundamental Invariants

These invariants are mandatory across the codebase:

1. **MODEL ≠ AGENT:** The model is an interchangeable computation engine; Jaeger is the persistent entity.
2. **SESSION ≠ AGENT:** Sessions belong to the Agent; the Agent never belongs to a session.
3. **PERSONA ≠ IDENTITY:** Persona modulates expressive style, voice, and character traits; Identity is the immutable per-instance anchor.
4. **MEMORY ≠ CONTEXT WINDOW:** Context windows are temporary scratchpads for active turns; Memory is persistent, structured, and selective.
5. **SKILL ≠ MEMORY:** Memory is autobiographical ("I solved this"); Skill is a tested, reusable procedure ("This is a verified procedure for this class of problem").
6. **PROPOSED ACTION ≠ AUTHORIZED ACTION:** The model proposes actions; the Authority Layer decides whether they are permitted.
7. **ATTEMPTED ACTION ≠ VERIFIED SUCCESS:** Model claiming success does not constitute success; verification requires ground-truth evidence, tests, and tool return validation.
8. **SENSOR INPUT ≠ TRUSTED FACT:** Telemetry is perceived as events; belief revision determines if it becomes settled truth.
9. **REFLECTION ≠ FACT:** Model-derived summaries retain provenance and evidence; they do not overwrite grounded facts.
10. **SUBAGENT ≠ NEW AGENT:** Spawned worker subagents act on behalf of the single persistent Agent unless intentionally instantiated with separate identity.
11. **EVENT ≠ LLM CALL:** The vast majority of events update state and persist with zero model invocations.
12. **IDLE ≠ INACTIVE ENTITY:** When the user is silent, the Agent perceives, reflects, consolidates memory, and maintains background vigilance.
13. **PROVIDER CHANGE ≠ IDENTITY CHANGE:** Changing providers (Hermes → Claude → Ollama) preserves the continuous Agent identity.
14. **INTERFACE CHANGE ≠ IDENTITY CHANGE:** Connecting via Mac App, WebUI, TUI, or CLI interacts with the same persistent Agent.

---

## 3. Jaeger Subsystem Alignment Map

Every major Jaeger subsystem maps directly to one of the canonical layers:

| Universal Architecture Layer | Canonical Role | Jaeger Implementation Components | Alignment Notes |
| :--- | :--- | :--- | :--- |
| **1. Agent Identity** | Unique, stable anchor surviving restarts, provider changes, sessions, and persona swaps. | `jaeger_ai/core/entity/identity.py` (`EntityIdentity`, `resolve_entity_identity`) | Class name `EntityIdentity` implements the **Agent Identity** concept. |
| **2. Event Fabric** | Chronological, append-only, replayable event stream with provenance. | `jaeger_ai/core/entity/events.py` (`JaegerEvent`), `jaeger_ai/core/entity/event_store.py` (`SqliteEventStore`) | Backed by durable SQLite in `<state_root>/entity_events.sqlite3`. |
| **3. Perception Layer** | Translates raw environmental and OS changes into normalized events. | `jaeger_ai/core/entity/sensors/` (`SensorAdapter`, `DesktopActivitySensor`), `jaeger_ai/features/reasoning/perception.py` | Tiered sensing: cheap telemetry → relevance → rich perception. |
| **4. Attention / Salience** | Decides whether an event warrants cognition or silent state reduction. | `jaeger_ai/core/entity/attention.py` (`SalienceEngine`, `AttentionDecision`) | Passive events update state with 0 model calls; salience $\ge 0.7$ wakes cognition. |
| **5. Self State** | Compact authoritative projection of current operational reality. | `jaeger_ai/core/entity/self_state.py` (`SelfState`), `jaeger_ai/core/entity/reducer.py` (`reduce_event`) | Deterministically rebuilt from event log on cold boot; zero fake consciousness claims. |
| **6. World Model** | Structured knowledge of entities, events, claims, and relations. | `packages/jaeger-agent/jaeger_agent/cognition/world.py` (`WorldModel`, `WorldEvent`, `Entity`, `Claim`, `Evidence`, `Relationship`) | Follows Panini-style structured semantic memory with provenance. |
| **7. Memory System** | Multi-tiered memory (Working, Episodic, Semantic, Procedural, Reflective). | `packages/jaeger-agent/jaeger_agent/memory/` (`sqlite_knowledge.py`, `retrieval.py`), `jaeger_ai/core/gateway/session_store.py` | Explicitly separates working prompt blocks from episodic transcripts and semantic graph claims. |
| **8. Executive** | Decides cognitive strategy (ReAct, Planning, Delegation, or Silent). | `packages/jaeger-agent/jaeger_agent/cognition/executive.py` (`TurnExecutive`), `jaeger_ai/core/runtime/autonomous_runner.py` | Orchestrates goals, commitments, budgets, and routing. |
| **9. Cognition Layer** | Selectable cognitive modes (ReAct, deliberative search, reflection, self-refine). | `packages/jaeger-agent/jaeger_agent/loop/jaeger_agent.py`, `jaeger_ai/features/reasoning/engine.py` | Employs ReAct for tool execution and reflective passes for idle reasoning. |
| **10. Cognition Providers** | Interchangeable, stateless LLM inference engines. | `packages/jaeger-agent/jaeger_agent/adapters/` (Hermes, Anthropic, OpenAI, Ollama, Local Llama) | Models are swappable without altering Agent Identity or Memory. |
| **11. Action / Tool System** | Dispatches authorized operations to tools and hardware. | `packages/jaeger-agent/jaeger_agent/tool_executor.py` (`HookedToolExecutor`, `LedgerToolExecutor`), `ToolDef` | Emits `tool.started` and `tool.completed`/`tool.failed` consequence events. |
| **12. Policy / Authority Boundary** | Deterministic gate enforcing permissions, limits, and safety. | `jaeger_ai/core/runtime/tool_repair.py`, `jaeger_agent.cognition.effects.EffectLedger`, `tool_allowlist`, subagent worktrees | Outside model discretion; models cannot grant themselves permissions. |
| **13. Verification Layer** | Ground-truth assertions verifying attempted actions. | `EffectLedger`, Checkpointing (`checkpoints.py`), execution verification fixtures, test assertions | An action is not complete until confirmed by independent tool verification. |
| **14. Learning Layer** | Updates persistent state, beliefs, and skills from verified experience. | `packages/jaeger-agent/jaeger_agent/skill_improvement/`, `jaeger_ai/core/entity/consolidation.py` | Preserves provenance; model opinions do not overwrite verified records. |
| **15. Skill Library** | Reusable, verified procedures and playbooks. | `jaeger_ai/core/entity/skills/promotion.py` (`SkillPromotionPipeline`), `packages/jaeger-agent/.../skill_registry/` | Voyager-style attempt → test verify → promote → retrieve lifecycle. |
| **16. Sleep-Time Processing** | Offline/idle memory consolidation, reflection, and indexing. | `jaeger_ai/core/entity/consolidation.py` (`MemoryConsolidator`), `jaeger_ai/core/runtime/heartbeat.py` (`execute_heartbeat_event`) | Idle processing extracts durable insights into WorldModel with zero chatter. |
| **17. Workers / Cognitive Subagents** | Delegated worker processes acting on behalf of the persistent Agent. | `packages/jaeger-agent/jaeger_agent/delegates/`, `subagent_worktree.py`, `jaeger_ai/core/agent_registry/` | Specialist workers act on behalf of the Agent without minting new persistent identities. |

---

## 4. Terminology Rules for JaegerAI

Future architecture documentation and commit messages must adhere to these conventions:

| Preferred Term | Prohibited / Deprecated Usage |
| :--- | :--- |
| **Agent** | *chatbot, assistant wrapper, LLM* |
| **Agent Identity** | *persona identity, character sheet identity* |
| **Event Fabric** | *turn system, message loop* |
| **Perception Layer** | *sensor hack, background poller* |
| **Attention / Salience** | *wake trigger hack* |
| **Self State** | *belief cache, global variable dump* |
| **World Model** | *memory blob, vector store* |
| **Executive** | *giant monolithic prompt* |
| **Cognition Provider** | *the AI, model identity* |
| **Action System** | *random tool collection* |
| **Authority Layer / Policy Kernel** | *system prompt warning* |
| **Verification Layer** | *model says it succeeded* |
| **Skill Library** | *prompt template folder* |
| **Sleep-Time Processing** | *endless background monologue* |

---

## 5. Architectural Stack Diagram

```
                   AGENT IDENTITY (EntityIdentity)
                                  │
                                  ▼
                     EVENT FABRIC (SqliteEventStore)
                                  │
                                  ▼
                     PERCEPTION (SensorAdapters)
                                  │
                                  ▼
                 ATTENTION / SALIENCE (SalienceEngine)
                                  │
             ┌────────────────────┴────────────────────┐
             │                                         │
       PASSIVE STORE                                 WAKE
             │                                         │
             ▼                                         ▼
         SELF STATE                                EXECUTIVE
             │                                         │
             ├──────────── WORLD MODEL ────────────────┤
             │                                         │
             ├──────────── MEMORY SYSTEM ──────────────┤
             │                                         │
             ▼                                         ▼
                                                COGNITION MODES
                                              (ReAct, Deliberate)
                                                       │
                                              cognition providers
                                              (Claude, Hermes...)
                                                       │
                                                       ▼
                                                 ACTION SYSTEM
                                                       │
                                                AUTHORITY LAYER
                                             (EffectLedger, Policy)
                                                       │
                                                       ▼
                                                  ENVIRONMENT
                                                       │
                                                       ▼
                                                   FEEDBACK
                                                       │
                                                       ▼
                                                 VERIFICATION
                                                       │
                                                       ▼
                                                   LEARNING
                                           ┌───────────┼───────────┐
                                           ▼           ▼           ▼
                                         memory      world       skills
                                                       │
                                                       ▼
                                             SLEEP-TIME PROCESSING
                                                 (Consolidation)
```
