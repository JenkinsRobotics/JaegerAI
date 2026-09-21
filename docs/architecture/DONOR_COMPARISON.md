# DONOR_COMPARISON.md — Public Architecture Comparative Analysis

**Evaluation Date:** 2026-09-20  
**Status:** Architectural Analysis & Benchmark Matrix  
**Specification Baseline:** Universal Persistent Agent Architecture (UPAA)

---

## 1. Architectural Matrix

| Dimension / Subsystem | Jaeger (Before Pinocchio) | Research Reference Systems | Jaeger (Pinocchio / UPAA Production) | Verification Test |
| :--- | :--- | :--- | :--- | :--- |
| **Top-Level Sovereign Authority** | `JaegerAgent` owned execution loop; entity was sidecar logger. | **Letta**: Central agent runtime owns memory, sessions, and tools. | **Inverted**: `EntityRuntime` is sovereign production authority; `JaegerAgent` is subordinate ReAct engine. | `test_1_real_executable_trace` |
| **Stable Agent Identity** | Fragmented across `Identity` & session stores; model owned identity. | **Letta**: Single `agent_id` owning all sessions and prompt blocks. | **Unified**: Stable `EntityIdentity` surviving cold boot; model != agent; dynamic prompt injection. | `test_4_provider_swap_continuity` |
| **Multi-Interface Ingress** | Competing execution pathways in Gateway, Bridge, CLI. | **Letta**: Unified server coordinator. | **Converged**: CLI, Bridge, Gateway, and Background tasks route through `EntityRuntime.execute_turn(...)`. | `test_5_interface_swap_shared_authority` |
| **Structured Failure Lessons** | Unstructured chat history / transient error strings. | **Reflexion**: Structured failure hypotheses with applicability conditions. | **ReflexionStore**: Durable hypotheses (`StructuredReflection`) with confidence scoring & dynamic planning retrieval. | `test_4_provider_swap_continuity`, `test_8_deliberate_planning_mode` |
| **Iterative Refinement** | Single-pass model outputs for all tasks. | **Self-Refine**: Generate -> critique -> revise -> validate cycle. | **SelfRefineEngine**: Selectively invoked by Executive for sensitive or irreversible mutations. | `test_8_deliberate_planning_mode` |
| **Deliberate Tree Search** | Single linear plan or direct ReAct dispatch. | **LATS / Agent S**: Multi-candidate generation, critic evaluation, tree exploration. | **DeliberatePlanner**: Generates $\ge 3$ candidate plans; critic scores goal, safety, reversibility, reflection penalty. | `test_8_deliberate_planning_mode` |
| **Procedural Skill Learning** | Manual authoring or static skill folder. | **Voyager**: Attempt -> feedback -> verify -> library promotion. | **Voyager Loop**: `SkillPromotionPipeline` verifies candidate, writes production `SKILL.md` to disk. | `test_7_voyager_skill_promotion_to_production_registry` |
| **Tiered Perception** | Un-gated telemetry or polling. | **ProactiveAgent / ProAgent**: Tiered sensing with salience gating. | **Tiered Perception**: Tier 0 (deterministic) -> Tier 1 (heuristics) -> Tier 2 (multimodal model) escalation. | `test_9_tiered_perception_escalation` |
| **Passive vs Active Sensing** | Narrow telemetry without salience thresholding. | **ActivityWatch / ProactiveAgent**: Low-overhead polling. | **SalienceEngine**: Routine telemetry consumes 0 model tokens; anomaly wakes cognition. | `test_2_passive_path_zero_model_calls`, `test_3_active_path_wakes_cognition` |
| **Offline Sleep-Time Processing** | Isolated belief state updates. | **Generative Agents**: Periodic memory stream consolidation. | **SleepTimeProcessor**: Heartbeat is trigger only; extracts claims, synthesizes reflections, handles contradiction. | `test_6_sleep_time_consolidation` |
| **Authority Ordering** | Tool permissions checked in executor during call. | **UPAA Invariant 5**: Proposed Action -> Authority -> Executor. | **AuthorityLayer**: Formal `ProposedAction` authorization pass before execution dispatch. | `test_audit_1_authority_ordering` |
| **Ground-Truth Verification** | Execution return (`ok=True`) treated as success. | **UPAA Invariant 7**: Verification != EffectLedger. | **VerificationContract**: Independent inspection of disk, git, process, or network state. | `test_1_real_executable_trace` |

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
