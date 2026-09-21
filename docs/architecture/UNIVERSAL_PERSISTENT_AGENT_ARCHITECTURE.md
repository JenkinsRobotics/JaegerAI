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

| Universal Architecture Layer | Canonical Role | Status | Jaeger Implementation Components | Behavioral Verification Proof |
| :--- | :--- | :--- | :--- | :--- |
| **1. Agent Identity** | Unique, stable anchor surviving restarts, provider changes, sessions, and persona swaps. | **VERIFIED** | `jaeger_ai/core/entity/identity.py` (`EntityIdentity`, `resolve_entity_identity`) | Verified in `dev/tests/test_pinocchio_entity.py::test_acceptance_a_identity_continuity` (persists cold reboot). |
| **2. Event Fabric** | Chronological, append-only, replayable event stream with provenance. | **VERIFIED** | `jaeger_ai/core/entity/events.py` (`JaegerEvent`), `jaeger_ai/core/entity/event_store.py` (`SqliteEventStore`) | Verified in `dev/tests/test_pinocchio_entity.py::test_acceptance_g_self_state_reconstruction` & `test_runtime_trace.py::test_audit_9_single_runtime_authority_trace`. |
| **3. Perception Layer** | Translates raw environmental and OS changes into normalized events via 3-tier escalation. | **VERIFIED** | `SensorAdapter`, `DesktopActivitySensor`, `TieredPerceptionCoordinator` (`sensors/tiered.py`) | Verified in `dev/tests/test_upaa_production_runtime.py::test_9_tiered_perception_escalation`. |
| **4. Attention / Salience** | Decides whether an event warrants cognition or silent state reduction. | **VERIFIED** | `jaeger_ai/core/entity/attention.py` (`SalienceEngine`, `AttentionDecision`) | Verified in `dev/tests/test_upaa_production_runtime.py::test_2_passive_path_zero_model_calls` & `test_3_active_path_wakes_cognition`. |
| **5. Self State** | Compact authoritative projection of current operational reality. | **VERIFIED** | `jaeger_ai/core/entity/self_state.py` (`SelfState`), `jaeger_ai/core/entity/reducer.py` (`reduce_event`) | Verified in `dev/tests/test_pinocchio_entity.py::test_acceptance_g_self_state_reconstruction` (exact deterministic replay). |
| **6. World Model** | Structured knowledge of entities, events, claims, and relations. | **VERIFIED** | `packages/jaeger-agent/jaeger_agent/cognition/world.py` (`WorldModel`, `WorldEvent`, `Entity`, `Claim`, `Evidence`, `Relationship`) | Verified in `dev/tests/test_upaa_production_runtime.py::test_6_sleep_time_consolidation`. |
| **7. Memory System** | 5-part memory taxonomy (Working, Episodic, Semantic, Reflective, Procedural). | **VERIFIED** | `jaeger_ai/core/entity/memory.py` (`MemorySubsystem`), `reflection.py` (`ReflexionStore`). Decouples transport session cache. | Verified in `dev/tests/test_runtime_trace.py::test_audit_3_memory_taxonomy_explicit_ownership` & `test_upaa_production_runtime.py::test_4_provider_swap_continuity`. |
| **8. Executive** | Decides cognitive strategy (Passive, Direct, ReAct, Deliberate, Delegation, Sleep). | **VERIFIED** | `jaeger_ai/core/entity/executive.py` (`ExecutiveStrategySelector`, `CognitiveStrategy`), `cognition_router.py` (`CognitionRouter`) | Verified in `dev/tests/test_runtime_trace.py::test_audit_4_executive_strategy_selection` & `test_upaa_production_runtime.py::test_1_real_executable_trace`. |
| **9. Cognition Modes** | Selectable cognitive modes (DirectResponse, ReAct, Deliberate Planning, Self-Refinement, Delegation). | **VERIFIED** | `CognitionRouter`, `DeliberatePlanner` (DeliberativeSearch $\ge 3$ candidate plans with critic evaluation & bounded replan), `SelfRefineEngine` (model-backed critique-revision loop), `ReflexionStore` | Verified in `dev/tests/test_upaa_production_runtime.py::test_8_deliberate_planning_mode` & `dev/tests/test_upaa_closure_pass.py::test_closure_deliberative_search_cognition_and_replan`. |
| **10. Cognition Providers** | Interchangeable, stateless LLM inference engines. | **VERIFIED** | `packages/jaeger-agent/jaeger_agent/adapters/` (Hermes, Claude, OpenAI, Ollama, Local Llama) | Verified in `dev/tests/test_pinocchio_entity.py::test_acceptance_b_provider_independence`. |
| **11. Action / Tool System** | Dispatches authorized operations to tools and hardware. | **VERIFIED** | `packages/jaeger-agent/jaeger_agent/tool_executor.py` (`DirectToolExecutor`, `LedgerToolExecutor`), `ToolDef` | Verified in `dev/tests/test_pinocchio_entity.py::test_acceptance_e_tool_consequence_loop` (`tool.started` and `tool.completed`). |
| **12. Policy / Authority Boundary** | Deterministic gate enforcing permissions and vetoes before execution. | **VERIFIED** | `jaeger_ai/core/entity/authority.py` (`AuthorityLayer`, `ProposedAction`), `HookedToolExecutor` (UPAA authority facade over real ToolExecutor, shell-hook vetoes, and permissions) | Verified in `dev/tests/test_runtime_trace.py::test_audit_1_authority_ordering` (`Proposed Action → Authority Layer → Action System`) & `test_audit_9_single_runtime_authority_trace`. |
| **13. Verification Layer** | Action-specific ground-truth assertions verifying real-world outcomes separate from tool exit codes. | **VERIFIED** | `jaeger_ai/core/entity/verification.py` (`VerificationContract`, `VerificationRegistry`). Action-specific probes for write, delete, git, process, http, read-only, and message send. Unknown returns `OBJECTIVE_UNVERIFIED`. | Verified in `dev/tests/test_runtime_trace.py::test_audit_2_verification_distinction` & `dev/tests/test_upaa_closure_pass.py::test_closure_action_specific_verification_registry`. |
| **14. Learning Layer** | Continuous conversion of verified experience into durable updates across memory, world, and skills. | **VERIFIED** | `jaeger_ai/core/entity/learning.py` (`LearningPipeline`, `LearningTarget`). | Verified in `dev/tests/test_runtime_trace.py::test_audit_7_learning_pipeline` (verified outcomes reinforce, failures generate lessons). |
| **15. Skill Library** | Reusable, verified procedures and operational playbooks promoted to production registry. | **VERIFIED** | `jaeger_ai/core/entity/skills/promotion.py` (`SkillPromotionPipeline`), production skill loader (`reload_skills()`) | Verified in `dev/tests/test_upaa_closure_pass.py::test_closure_skill_promotion_and_restart_discovery` (v3 manifest, SKILL.md, smoke test, and restart discovery). |
| **16. Sleep-Time Processing** | Offline/idle memory consolidation, reflection, and indexing (heartbeat as trigger only). | **VERIFIED** | `jaeger_ai/core/entity/sleep_time.py` (`SleepTimeProcessor`), `jaeger_ai/core/entity/consolidation.py` (`MemoryConsolidator`) | Verified in `dev/tests/test_runtime_trace.py::test_audit_6_sleep_time_processing` (triggered by heartbeat, executes consolidation/reflection). |
| **17. Single Runtime Authority** | Single process-wide runtime coordinator unifying all ingress interfaces into one persistent entity. | **VERIFIED** | `jaeger_ai/core/entity/runtime.py` (`EntityRuntime` singleton). | Verified in `dev/tests/test_runtime_trace.py::test_audit_9_single_runtime_authority_trace` (CLI, Bridge, Gateway, Heartbeat, Background, Passive/Salient Sensors). |

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
                                              (ReAct, Deliberate,
                                            Reflection, Delegation)
                                                        │
                                               cognition providers
                                               (Claude, Hermes...)
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
                                                    FEEDBACK
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
                                            ┌───────────┼───────────┐
                                            ▼           ▼           ▼
                                          memory      world       skills
                                                       │
                                                       ▼
                                             SLEEP-TIME PROCESSING
                                                 (Consolidation)
```
