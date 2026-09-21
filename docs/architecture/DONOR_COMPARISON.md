# DONOR_COMPARISON.md — Public Architecture Comparative Analysis

**Evaluation Date:** 2026-09-20  
**Status:** Architectural Analysis & Benchmark Matrix  
**Specification Baseline:** Universal Persistent Agent Architecture (UPAA)

---

## 1. Architectural Matrix

| Dimension / Subsystem | Jaeger (Before Pinocchio) | Research Reference Systems | Jaeger (Pinocchio / UPAA Production) | Verification Test |
| :--- | :--- | :--- | :--- | :--- |
| **Top-Level Sovereign Authority** | `JaegerAgent` owned execution loop; entity was sidecar logger. | **Letta**: Central agent runtime owns memory, sessions, and tools. | **Inverted**: `EntityRuntime` is sovereign production authority; `JaegerAgent` is subordinate ReAct engine. | `test_1_real_executable_trace` |
| **Stable Agent Identity** | Fragmented across `Identity` & session stores; model owned identity. | **Letta**: Single `agent_id` owning all sessions and prompt blocks. | **Unified**: Stable `EntityIdentity` surviving cold boot; model != agent; dynamic prompt injection. | `test_4_provider_swap_continuity`, `test_closure_provider_routing_swap` |
| **Multi-Interface Ingress** | Competing execution pathways in Gateway, Bridge, CLI. | **Letta**: Unified server coordinator. | **Converged**: CLI (`_run_turn`), Bridge (`run_for_voice`), Gateway (`_execute_turn`), and Background tasks route through `EntityRuntime.execute_turn(...)`. Zero duplicate events. | `test_audit_9_single_runtime_authority_trace` |
| **Structured Failure Lessons** | Unstructured chat history / transient error strings. | **Reflexion**: Structured failure hypotheses with applicability conditions. | **ReflexionStore**: Durable hypotheses (`StructuredReflection`) with confidence scoring & dynamic planning retrieval. | `test_4_provider_swap_continuity`, `test_closure_deliberative_search_cognition_and_replan` |
| **Iterative Refinement** | Single-pass model outputs for all tasks. | **Self-Refine**: Generate -> critique -> revise -> validate cycle. | **SelfRefineEngine**: Model-backed critic and reviser callbacks execute iterative refinement loop for sensitive artifacts. | `test_closure_self_refine_model_critic_and_reviser` |
| **Deliberate Tree Search** | Single linear plan or direct ReAct dispatch. | **LATS / Agent S**: Multi-candidate generation, critic evaluation, tree exploration. | **DeliberativeSearch**: Generates $\ge 3$ candidate plans via cognition provider; critic scores goal, safety, reversibility; bounded replanning on failure. | `test_closure_deliberative_search_cognition_and_replan` |
| **Procedural Skill Learning** | Manual authoring or static skill folder. | **Voyager**: Attempt -> feedback -> verify -> library promotion. | **Voyager Loop**: `SkillPromotionPipeline` writes full v3 skill package (`manifest.yaml`, `SKILL.md`, `run.py`, smoke test), registers into production `reload_skills()`, and survives restart. | `test_closure_skill_promotion_and_restart_discovery` |
| **Tiered Perception** | Un-gated telemetry or polling. | **ProactiveAgent / ProAgent**: Tiered sensing with salience gating. | **Tiered Perception & Supervisor**: Tier 0 (0 models) -> Tier 1 (local heuristics) -> Tier 2 (model callback on justified escalation) with privacy scrubbing. Background `SensorSupervisor`. | `test_closure_tiered_perception_and_privacy_redaction`, `test_closure_sensor_supervisor_lifecycle` |
| **Passive vs Active Sensing** | Narrow telemetry without salience thresholding. | **ActivityWatch / ProactiveAgent**: Low-overhead polling. | **SalienceEngine**: Routine telemetry consumes 0 model tokens; anomaly wakes cognition. | `test_2_passive_path_zero_model_calls`, `test_3_active_path_wakes_cognition` |
| **Offline Sleep-Time Processing** | Isolated belief state updates. | **Generative Agents**: Periodic memory stream consolidation. | **SleepTimeProcessor**: Heartbeat is trigger only; extracts claims, synthesizes reflections, handles contradiction. | `test_6_sleep_time_consolidation`, `test_audit_6_sleep_time_processing` |
| **Authority Ordering** | Tool permissions checked in executor during call. | **UPAA Invariant 5**: Proposed Action -> Authority -> Executor. | **AuthorityLayer & HookedToolExecutor**: UPAA authority facade wraps permissions, shell-hook vetoes, and arguments before `EffectLedger` claims effect. | `test_audit_1_authority_ordering`, `test_audit_9_single_runtime_authority_trace` |
| **Ground-Truth Verification** | Execution return (`ok=True`) treated as success. | **UPAA Invariant 7**: Verification != EffectLedger. | **VerificationRegistry**: Action-specific ground-truth probes (write, delete, git, process, http, read-only, message). Unknown strictly returns `OBJECTIVE_UNVERIFIED`. | `test_closure_action_specific_verification_registry` |

---

## 2. Detailed Subsystem Evaluations & Donor Disposition

### A. Letta (MemGPT)
* **What they do better:** Agent-first entity model where memory, context blocks, and tools belong to the persistent identity rather than the chat session.
* **What Jaeger does better:** Local-first embodied execution, AF_UNIX bridge, EffectLedger idempotency, zero-in-repo state architecture.
* **Decision:** **ADAPT & INVERT**. Control plane inverted so `EntityRuntime` is top-level sovereign authority and `JaegerAgent` is subordinate. Live `<self>` block injected into prompts via `assemble_prompt`.

### B. Reflexion
* **What they do better:** Explicit failure hypotheses with applicability conditions preventing agents from repeating known mistakes.
* **What Jaeger does better:** Verified multi-tool execution and robust shell tool repair.
* **Decision:** **PORT & ADAPT**. Implemented `StructuredReflection` and `ReflexionStore` (`reflection.py`) with automatic failure hypothesis synthesis and dynamic prompt retrieval.

### C. Self-Refine
* **What they do better:** Multi-pass self-critique and revision improving code and plan quality.
* **What Jaeger does better:** Lean single-pass efficiency for routine chat turns.
* **Decision:** **PORT & ADAPT**. Implemented `SelfRefineEngine` (`self_refine.py`), invoked selectively by Executive for high-stakes or irreversible operations.

### D. Voyager
* **What they do better:** Autonomous procedural skill acquisition with environmental feedback and test gates.
* **What Jaeger does better:** Production-ready playbook skill system with markdown frontmatter and sandboxing.
* **Decision:** **ADAPT TO PRODUCTION REGISTRY**. Implemented `SkillPromotionPipeline` (`skills/promotion.py`) writing real production `SKILL.md` files into the instance skill library upon passing automated verification.

### E. Agent S / S2 & LATS
* **What they do better:** Hierarchical planning and deliberate candidate plan search under complex computer-use scenarios.
* **What Jaeger does better:** Mature ReAct execution loop, tool repairing, context budgeting, and work ledgers.
* **Decision:** **ADAPT**. Implemented `DeliberatePlanner` (`deliberate_planner.py`) generating $\ge 3$ candidate plans evaluated by an independent critic before subordinate execution.
