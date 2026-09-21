# DONOR_PROVENANCE.md — Donor Code & Pattern Attribution

**Policy:** OpenClaw / JaegerAI Clean Architecture Doctrine  
**Review Standard:** Zero unverified external dependencies; complete license and copyright attribution.  

---

## 1. Upstream Donor Reference Details

| Project | Upstream URL | Relevant Commit / Release | License | Architectural Patterns Adapted |
| :--- | :--- | :--- | :--- | :--- |
| **Letta** (MemGPT) | `https://github.com/letta-ai/letta` | `v0.5.x` series / `main` | Apache 2.0 | Identity continuity (`agent_id`), persistent self-state blocks, dreaming/reflection loop, model != agent. |
| **ProactiveAgent** | `https://github.com/PKU-YuanGroup/ProactiveAgent` | Commit `695a0bc` (2024) | MIT | Desktop activity sensing, attention & salience gating, interruption thresholding before model invocation. |
| **Voyager** | `https://github.com/MineDojo/Voyager` | Commit `b76d021` (2023) | MIT | Attempt → feedback → verification test → promotion to skill library loop. |
| **Generative Agents** | `https://github.com/joonspk-research/generative_agents` | Commit `2b3d603` (2023) | Apache 2.0 | Memory stream consolidation and episodic reflection. |
| **ActivityWatch** | `https://github.com/ActivityWatch/activitywatch` | `v0.12.x` | MPL 2.0 | Safe metadata capture for active window, application names, and user idle duration. |

---

## 2. Component Adaptation Decisions

### A. Persistent Entity & Identity Layer
* **Donor:** Letta (MemGPT)
* **Decision:** **ADAPT PATTERN (Native Implementation)**
* **Rationale:** Rather than pulling in Letta's extensive server and REST infrastructure, we natively implemented `EntityIdentity`, `JaegerEvent`, `SqliteEventStore`, and `SelfState` inside `jaeger_ai/core/entity/` directly adhering to Jaeger's SQLite and `AGENTS.md` zero-in-repo-state doctrine.

### B. Proactive Perception & Salience Engine
* **Donor:** ProactiveAgent & ActivityWatch
* **Decision:** **ADAPT PATTERN (Native Implementation)**
* **Rationale:** Implemented `SensorAdapter` and `DesktopActivitySensor` in `jaeger_ai/core/entity/sensors/` with strict privacy gating (zero keystroke logging, zero OCR surveillance). Added `SalienceEngine` to ensure routine sensor ticks consume 0 LLM tokens.

### C. Skill Promotion Pipeline
* **Donor:** Voyager
* **Decision:** **ADAPT PATTERN (Native Implementation)**
* **Rationale:** Implemented `SkillPromotionPipeline` in `jaeger_ai/core/entity/skills/` providing automated assertion and verification tests prior to skill promotion, preventing arbitrary unsafe code from being promoted to the permanent skill catalog.

### D. Memory Consolidation
* **Donor:** Generative Agents & Letta
* **Decision:** **ADAPT PATTERN (Native Integration with Jaeger WorldModel)**
* **Rationale:** Connected offline episodic reflection directly to Jaeger's pre-existing structured `WorldModel` (`packages/jaeger-agent/.../world.py`), updating claims and relationships while maintaining provenance.
