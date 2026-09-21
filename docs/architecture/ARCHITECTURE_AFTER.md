# ARCHITECTURE_AFTER.md — Pinocchio Persistent Entity Runtime Architecture

**Document Version:** 2.0.0 (Universal Persistent Agent Architecture Production Implementation)  
**Author:** Principal Systems Architect  
**Status:** Canonical Production Architecture  
**Reference Specification:** [Universal Persistent Agent Architecture (UPAA)](UNIVERSAL_PERSISTENT_AGENT_ARCHITECTURE.md)

---

## 1. Executive Summary: The Sovereign Entity Runtime

In the `pinocchio` release, JaegerAI has completed a full production refactor into the **Universal Persistent Agent Architecture (UPAA)**.

The control plane inversion is complete:
- **`EntityRuntime`** is the top-level sovereign authority and sole lifecycle coordinator.
- **`JaegerAgent`** is demoted to a subordinate cognitive engine used by the runtime when `CognitiveStrategy.REACT_LOOP` is selected.
- All production ingress paths (CLI, Bridge, Gateway, Web UI, voice, background workers, and heartbeats) execute through `EntityRuntime.execute_turn(...)`.

### Canonical Runtime Control Path

```
EVENT
  │
  ▼
EVENT FABRIC (SqliteEventStore append-only WAL)
  │
  ▼
PERSISTENCE & DETERMINISTIC STATE REDUCTION
  │
  ▼
SELF STATE & WORLD MODEL UPDATE
  │
  ▼
ATTENTION & SALIENCE ENGINE
  │
  ├────────────────────────────────────────┬────────────────────────────────────────┐
  ▼                                        ▼                                        ▼
[Salience < 0.3]                    [Routine Anomaly]                      [Salience >= 0.6]
Passive Record                      Tiered Perception Escalation           EXECUTIVE STRATEGY SELECTION
(0 LLM Tokens)                      (Tier 0 -> Tier 1 -> Tier 2)           (ExecutiveStrategySelector)
                                                                                    │
                                           ┌────────────────────────────────────────┼────────────────────────────────────────┐
                                           ▼                                        ▼                                        ▼
                                     Direct Response                            ReAct Loop                           Deliberate Planner
                                 (Informational Queries)                   (Subordinate JaegerAgent)              (LATS Tree-Search >= 3 Plans)
                                           │                                        │                                        │
                                           └────────────────────────────────────────┼────────────────────────────────────────┘
                                                                                    │
                                                                                    ▼
                                                                           COGNITION ROUTER
                                                                     (Canonical Strategy Boundary)
                                                                                    │
                                                                                    ▼
                                                                             PROPOSED ACTION
                                                                                    │
                                                                                    ▼
                                                                             AUTHORITY LAYER
                                                                       (Deterministic Safety Policies)
                                                                                    │
                                                                                    ▼
                                                                              ACTION SYSTEM
                                                                         (ToolExecutor / Sandboxing)
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
                                                                      (Episodic, Semantic, Reflective)
                                                                                    │
                                                                                    ▼
                                                                           SLEEP-TIME PROCESSING
                                                                   (Offline Consolidation & Skill Gates)
```

---

## 2. Integrated Research Subsystems & Donor Implementations

### A. Persistent Agent Identity & Prompt Hierarchy (Letta / MemGPT)
* **Identity Decoupling:** `EntityIdentity` anchored at `<state_root>/entity_identity.json` maintains persistent identity across model swaps and host reboots.
* **Canonical Prompt Assembly:** `packages/jaeger-agent/jaeger_agent/prompts/assemble.py` dynamically injects:
  1. `entity_self_state`: live current facts, active goals, and commitments via `runtime.current_state.to_prompt_context_block()`.
  2. `retrieved_reflections`: failure warnings via `ReflexionStore.to_prompt_context_block(query)`.
* **Zero Model Ownership:** Models do not own or authoritatively mutate the agent's identity.

### B. Structured Failure Reflection (Reflexion)
* **Hypothesis Store:** `ReflexionStore` (`reflection.py`) maintains `StructuredReflection` entries containing `hypothesis`, `confidence`, `failure_conditions`, `applicability_conditions`, and episode provenance.
* **Adaptive Retrieval:** Automatically queries applicable reflections when planning similar tasks to avoid repeating known failure modes.

### C. Deliberate Tree-Search Planning (LATS / Agent S)
* **Candidate Plan Generation:** `DeliberatePlanner` (`deliberate_planner.py`) generates $\ge 3$ distinct execution strategies with varied tool choices.
* **Independent Critic:** Evaluates candidates across goal satisfaction, safety blast radius, reversibility, and prior reflection penalties.
* **Refinement Engine:** Uses `SelfRefineEngine` (`self_refine.py`) to iteratively critique and expand plans with sensitive or irreversible mutations.

### D. Procedural Skill Acquisition (Voyager)
* **Automated Promotion:** `SkillPromotionPipeline` (`skills/promotion.py`) gates skill candidates behind automated verification assertions.
* **Production Registry:** Verified skills are written as standard `SKILL.md` frontmatter and executable artifacts into the instance skills folder (`~/.jaeger/skills/`), instantly available to production loaders.

### E. Tiered Environmental Perception (ProactiveAgent / ProAgent)
* **Tier 0:** Cheap deterministic desktop metadata (idle time, active window, disk telemetry).
* **Tier 1:** Local heuristic classification of alerts and anomalies.
* **Tier 2:** Expensive multimodal / model assessment only when justified by critical conditions.

### F. Offline Consolidation (Generative Agents & Sleep-Time Compute)
* **Decoupled Triggers:** Heartbeats act as a trigger signal; `SleepTimeProcessor` (`sleep_time.py`) owns consolidation semantics.
* **Unified Pipeline:** Consolidates episodic events into semantic claims, detects contradictions, synthesizes reflections, and checks skill candidate assertions.

---

## 3. Production Ingress Unification

Every production turn entry point converges through `EntityRuntime.execute_turn(...)`:
- **CLI (`main.run_command`):** Calls `_run_turn` -> `EntityRuntime.execute_turn(...)`.
- **Bridge (`bridge.py`):** Drives turns via `_run_turn` -> `EntityRuntime.execute_turn(...)`.
- **Gateway (`server.py`):** Leads via native MCP `chat` -> `run_for_voice` -> `_run_turn` -> `EntityRuntime.execute_turn(...)`.
- **Background Workers / Crons:** Call `run_worker_turn` -> `_run_turn` -> `EntityRuntime.execute_turn(...)`.

There are zero parallel or competing runtime authorities.

---

## 4. Verification & Continuous Validation

All UPAA requirements are validated by automated end-to-end integration tests:
- `dev/tests/test_upaa_production_runtime.py`: 9 comprehensive tests validating real trace execution, 0-model passive paths, active cognition wake, provider swap continuity, interface swap identity sharing, sleep-time processing, Voyager skill promotion, deliberate planning, and tiered perception escalation.
- `dev/tests/test_runtime_trace.py`: 7 semantic audit tests validating authority ordering, verification contracts, memory taxonomy, and executive strategy selection.
