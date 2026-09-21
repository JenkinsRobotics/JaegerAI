# DONOR_PROVENANCE.md — Donor Code & Pattern Attribution

**Policy:** OpenClaw / JaegerAI Clean Architecture Doctrine  
**Review Standard:** Zero unverified external dependencies; surgical porting and pattern adaptation; full license and commit SHA attribution.

---

## 1. Upstream Donor Repositories Cataloged & Inspected

All donor repositories were cloned into `.donors/` (gitignored, outside source tree) and inspected directly at exact commits:

| Donor System | Repository URL | Exact Commit SHA | License | Primary Architectural Contribution |
| :--- | :--- | :--- | :--- | :--- |
| **Letta** (MemGPT) | `https://github.com/letta-ai/letta.git` | `5bcdd177` | Apache 2.0 | Persistent agent identity (`agent_id`), model != agent, live `<self>` memory block injection, multi-session continuity. |
| **Generative Agents** | `https://github.com/joonspk-research/generative_agents.git` | `fe05a71d` | Apache 2.0 | Autobiographical memory stream, importance scoring, periodic sleep-time reflection. |
| **Reflexion** | `https://github.com/noahshinn/reflexion.git` | `218cf0ef` | MIT | Structured failure hypotheses (`StructuredReflection`), applicability conditions, confidence updating, failure retrieval. |
| **Self-Refine** | `https://github.com/madaan/self-refine.git` | `9a206d41` | Apache 2.0 | Iterative `generate -> critique -> revise -> validate` loop (`SelfRefineEngine`) for sensitive plans and artifacts. |
| **Voyager** | `https://github.com/MineDojo/Voyager.git` | `55e45a88` | MIT | Procedural skill acquisition: candidate extraction, automated verification gate, promotion to production `SKILL.md`. |
| **Agent S / S2** | `https://github.com/simular-ai/Agent-S.git` | `3aa272d2` | Apache 2.0 | Hierarchical executive planning, specialist routing, computer-use task decomposition. |
| **ProactiveAgent** | `https://github.com/PKU-YuanGroup/ProactiveAgent.git` | `695a0bc` | MIT | Desktop activity perception, privacy filtering, salience threshold gating. |
| **ActivityWatch** | `https://github.com/ActivityWatch/activitywatch.git` | `v0.12.x` | MPL 2.0 | Low-overhead desktop metadata polling (active app, idle time, system telemetry). |

---

## 2. Research-to-Subsystem Decision Records

### Subsystem: Persistent Entity & Context Hierarchy (Letta / MemGPT)
* **Current Jaeger:** Fragmented session state and persona layers; model owned chat loop.
* **Donor:** Letta (`.donors/letta`) @ `5bcdd177` (Apache 2.0)
* **Files Inspected:** `letta/agent.py`, `letta/memory.py`, `letta/schemas/agent.py`
* **Decision:** **ADAPT & INVERT**
* **Reason:** Inverted runtime control hierarchy so `EntityRuntime` is top-level sovereign authority and `JaegerAgent` is subordinate. Directly integrated Letta's core `<self>` prompt block into `packages/jaeger-agent/jaeger_agent/prompts/assemble.py` via `_entity_self_state`.

### Subsystem: Structured Failure Reflection (Reflexion)
* **Current Jaeger:** Freeform text logs without structured hypothesis or applicability conditions.
* **Donor:** Reflexion (`.donors/reflexion`) @ `218cf0ef` (MIT)
* **Files Inspected:** `hotpot_reflexion.py`, `alfworld_runs/prompts/`, `reflexion.py`
* **Decision:** **PORT & ADAPT**
* **Reason:** Created `jaeger_ai/core/entity/reflection.py` with `StructuredReflection` containing hypothesis, confidence, failure_conditions, applicability_conditions, and episode provenance. Integrated directly into `ReflexionStore` and prompt assembly (`_retrieved_reflections`).

### Subsystem: Iterative Refinement (Self-Refine)
* **Current Jaeger:** Single-pass generation for all outputs.
* **Donor:** Self-Refine (`.donors/self-refine`) @ `9a206d41` (Apache 2.0)
* **Files Inspected:** `src/models/`, `src/eval.py`, `src/utils.py`
* **Decision:** **PORT & ADAPT**
* **Reason:** Implemented `SelfRefineEngine` in `jaeger_ai/core/entity/self_refine.py`. Selectively invoked by Executive for high-stakes or irreversible actions rather than taxing routine chat turns.

### Subsystem: Deliberate Planning (LATS / Tree-Search)
* **Current Jaeger:** Single linear plan or direct ReAct loop.
* **Donor:** Language Agent Tree Search & Agent S (`.donors/agent-s`) @ `3aa272d2` (Apache 2.0)
* **Files Inspected:** `gui_agent/`, `agent_s/`
* **Decision:** **ADAPT**
* **Reason:** Implemented `DeliberatePlanner` in `jaeger_ai/core/entity/deliberate_planner.py` generating $\ge 3$ candidate plans, evaluating with independent critic for goal satisfaction, safety, reversibility, and reflection penalties.

### Subsystem: Procedural Skill Learning (Voyager)
* **Current Jaeger:** Static skill folder or manual authoring.
* **Donor:** Voyager (`.donors/voyager`) @ `55e45a88` (MIT)
* **Files Inspected:** `voyager/agents/skill.py`, `voyager/agents/critic.py`
* **Decision:** **ADAPT TO PRODUCTION REGISTRY**
* **Reason:** Implemented `SkillPromotionPipeline` in `jaeger_ai/core/entity/skills/promotion.py`. Promoted skills write real production `SKILL.md` frontmatter and executable artifacts directly into Jaeger's instance skills folder (`~/.jaeger/skills/` or instance path), immediately discoverable by existing skill loaders.

### Subsystem: Tiered Desktop Perception (ProactiveAgent / ProAgent)
* **Current Jaeger:** Ad-hoc polling or reactive commands only.
* **Donor:** ProactiveAgent & ProAgent (`.donors/` reference)
* **Files Inspected:** ActivityWatch watchers and sensor adapters
* **Decision:** **ADAPT**
* **Reason:** Implemented generic 3-tier perception architecture in `jaeger_ai/core/entity/sensors/tiered.py` (Tier 0: Deterministic signals -> Tier 1: Local heuristic/classification -> Tier 2: Expensive multimodal/model synthesis).
