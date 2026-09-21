# DONOR_COMPARISON.md — Public Architecture Comparative Analysis

**Evaluation Date:** 2026-09-20  
**Status:** Architectural Analysis & Benchmark Matrix  

---

## 1. Architectural Matrix

| Feature | Jaeger (Before) | Reference System | Jaeger (Pinocchio / After) | Demonstrated Evidence |
| :--- | :--- | :--- | :--- | :--- |
| **Stable Agent Identity** | Fragmented across `Identity` (hardcoded "Lilith") & session stores. | **Letta**: Single `agent_id` owning all sessions, context, and memory blocks. | **Unified**: Stable `EntityIdentity` with unique `entity_id` surviving cold reboots. Decoupled from persona & model. | `test_acceptance_a_identity_continuity` |
| **Model / Provider Swapping** | Sessions could disconnect; persona and config tied to local/remote paths. | **Letta**: Model changes do not define the agent identity. | **Model-Independent**: Swapping Hermes -> Claude -> Ollama maintains exact same identity and memory stream. | `test_acceptance_b_provider_independence` |
| **Multi-Interface Authority** | 4 competing execution routes (Gateway, Bridge, MCP, Autonomous). | **Letta**: Unified agent server. | **Converged**: Gateway, Bridge, and CLI submit events to single `EntityRuntime`. | `test_acceptance_c_interface_independence`, `test_acceptance_l_multi_runtime_convergence` |
| **Heartbeat Truth** | Synthetic human user prompts (`"(Heartbeat)..."`). | **Letta**: Scheduled sleep-time & heartbeat events. | **Grounded**: Canonical `system.heartbeat` event; quiet beat updates state with 0 LLM calls. | `test_acceptance_d_heartbeat_truth` |
| **Tool Consequence Loop** | Tool returns consumed in local loop only; no durable event record. | **Jaeger**: Stronger safety ledger (`EffectLedger`, checkpoints). | **Grounded Consequence**: `tool.started` and `tool.completed/failed` logged to event store; affects uncertainty. | `test_acceptance_e_tool_consequence_loop` |
| **Background Continuity** | Background messages dropped into outbox; separate session bindings. | **Letta**: Background tasks tied to `agent_id`. | **Continuous**: Background tasks emit `background.completed` with provenance linked to entity history. | `test_acceptance_f_background_continuity` |
| **Self-State Reconstruction** | Volatile in-memory state; partial JSON caches. | **Letta**: SQLite state database. | **Reconstructed**: Cold reboot replays `SqliteEventStore` through pure reducers to restore `SelfState`. | `test_acceptance_g_self_state_reconstruction` |
| **Passive vs Active Sensing** | Narrow telemetry (git dirty files, disk GB); no gating. | **ProactiveAgent**: ActivityWatcher desktop sensing + interruption gating. | **SensorAdapter**: Desktop activity sensor + `SalienceEngine` gating (passive = 0 LLM calls; anomaly = wake). | `test_acceptance_h_passive_event_without_llm`, `test_acceptance_i_salient_event_wakeup` |
| **Between-Turn Consolidation** | Reasoning ticks isolated in `ares/belief_state.json`. | **Generative Agents**: Observation → memory stream → reflection loop. | **Dreaming**: `MemoryConsolidator` extracts claims/relations into `WorldModel` with provenance. | `test_acceptance_j_memory_consolidation` |
| **Continual Skill Learning** | Skill registry & benchmarks existed without closed loop. | **Voyager**: Attempt → feedback → verify → library promotion. | **Voyager Loop**: `SkillPromotionPipeline` extracts candidate, runs verification assertions, promotes to library. | `test_acceptance_k_skill_acquisition` |
| **Structured World Knowledge** | `WorldEvent` and `WorldModel` existed but were isolated from gateway. | **Panini**: Entity/event/claim graph with provenance. | **Fully Integrated**: `WorldModel` integrated into entity event stream; `belief_state.json` demoted to derived projection. | `test_acceptance_j_memory_consolidation` |
| **Embodied Safety & Integrity** | Strong (EffectLedger, tool permissions, AF_UNIX bridge). | Research systems lack fail-closed system engineering. | **Retained & Strengthened**: Existing safety mechanisms preserved; combined with entity continuity. | Complete regression and unit test suites pass. |

---

## 2. Detailed Subsystem Evaluations

### Letta (MemGPT lineage)
* **What they do better:** Elegant agent-centric mental model (`agent_id` owns memory, conversations, schedules, and tools).
* **What Jaeger does better:** Local-first embodied execution, audio/sensor nodes, EffectLedger transactionality, native macOS UI integration.
* **What we adopted:** `EntityIdentity` decoupled from model; memory blocks / `SelfState` projection; persistent event log.
* **What we rejected:** Cloud-first multi-tenant abstraction layers, external daemon runtime wrapper.

### ProactiveAgent
* **What they do better:** Continuous user activity sensing and proactive assistance based on ActivityWatcher signals.
* **What Jaeger does better:** Robust local security boundaries and fail-closed permission gates.
* **What we adopted:** SensorAdapter contract; safe desktop context metadata (idle seconds, active app); salience thresholding.
* **What we rejected:** Covert keystroke logging, unbounded screen capture, raw un-gated model triggers.

### Voyager
* **What they do better:** Clean iterative loop of code generation, verification against environmental feedback, and reusable skill promotion.
* **What Jaeger does better:** Rich tool schemas, subagent execution boundaries, sandbox worktrees.
* **What we adopted:** Automated verification test gate before promoting candidate skills; persistent skill library retrieval.
* **What we rejected:** Game-specific execution assumptions, unverified promotion of arbitrary execution side-effects.

### Generative Agents
* **What they do better:** Ablation-proven reflection loop synthesizing memories into higher-order thoughts.
* **What Jaeger does better:** Real-world tool use, grounded operating system interaction.
* **What we adopted:** Offline consolidation pass ("Dreaming") scoring and summarizing episodic events.
* **What we rejected:** Un-grounded floating-point simulation variables without real-world telemetry.

### Panini
* **What they do better:** Formal research validation for structured entity/event/claim memory.
* **What Jaeger does better:** Jaeger independently developed `WorldEvent`, `Entity`, `Claim`, `Evidence`, `Relationship`, and provenance in `packages/jaeger-agent/`.
* **What we adopted:** Fully wired `WorldModel` into the canonical entity event stream.
* **What we rejected:** Replacing structured symbolic graphs with opaque vector-only retrieval.
