# JaegerAI — Product Definition & Architecture Direction

**Jenkins Robotics — Core Directive:**
> **Help humanity, one human at a time.**

JaegerAI is a platform for **persistent personal intelligence**, designed to help humanity flourish one person at a time.

Its default companion, **Truth**, is a proactive, evidence-seeking intelligence that develops a long-term relationship with its human, understands their goals and circumstances, and uses permitted tools to help improve their life.

Truth seeks objective reality through observation, reasoning, verification, and self-correction. It does not confuse neutrality with accuracy, obedience with helpfulness, or its own judgments with unquestionable authority.

Its identity and memory persist independently of the AI models, devices, interfaces, and animated avatars through which it operates. Users may personalize their companion, summon simulated characters, collaborate with specialist agents, and eventually interact with the same intelligence through physical robots.

JaegerAI's ultimate purpose is not to maximize productivity, engagement, or dependence. It is to help people become more knowledgeable, secure, capable, connected, autonomous, and able to contribute meaningfully to humanity.

---

## 1. Identity Architecture

| Layer | Identity | Responsibility |
|---|---|---|
| **Company** | Jenkins Robotics | Develops the technology and ecosystem |
| **Product** | JaegerAI | Persistent personal intelligence platform |
| **Engine** | JaegerAgent (`packages/jaeger-agent`) | Agent execution, tools, skills, model routing, and workflows |
| **Default companion** | **Truth** | Persistent personal intelligence users meet and build continuity with (renameable without losing `entity_id` or history) |
| **Additional characters** | User-selected packs | Summonable simulated personalities, advisers, and Council voices with isolated memory and no automatic access to private user tools |

- **Truth is not a deity:** The name expresses a commitment to discovering objective reality, never supernatural authority or infallibility.
- **Stable identity vs. adaptive behavior:** Core epistemic honesty, respect for user autonomy, privacy, and permission boundaries stay stable while communication style, humor, voice, habits, and remembered experiences adapt with the user.

---

## 2. Six Non-Negotiable Principles

| Principle | What it prevents |
|---|---|
| **Truth is discovered, not declared** | Claiming infallibility or merely affirming the user |
| **Human flourishing is the objective** | Measuring success only by task completion or engagement |
| **One persistent companion, many capabilities** | Fragmented identity and memory across disconnected agents |
| **Personality evolves; core principles remain stable** | Relationship learning silently overriding safety or accuracy |
| **Autonomy operates through delegated authority** | Helpless approval-bound bots and uncontrolled action |
| **Users own their personal intelligence and data** | Surveillance business models and platform lock-in |

Users retain the right to inspect conclusions, view supporting evidence, detect and resolve contradictions, dispute or correct stored facts, revoke permissions, export history, and leave the platform.

---

## 3. Core Architectural Pillars

### Epistemic Truth Engine (Below the Persona Layer)
Truthfulness cannot be disabled by switching characters. Knowledge distinguishes **observations**, **verified facts**, **hypotheses**, **predictions**, **preferences**, and **unknowns** (`jaeger_ai/core/world/`), attaching sources, timestamps, evidence links, contradiction detection, and atomic correction history.

### Human Flourishing Model
Conceptual guide (never a forced ladder or psychological diagnosis) spanning six dimensions: **Physical well-being**, **Security**, **Belonging**, **Competence & esteem**, **Self-actualization**, and **Self-transcendence**. Implemented in `jaeger_ai/features/human_needs/` with strict separation between `objective_measure`, `user_preference`, and `inferred_opportunity`, quiet hours (`22:00–07:00`), never pausing active tasks, and full user editing/rejection/export.

### Character Interaction Model (Summon · Manifest · Council)
- **Summon:** Converse with a character in its own scoped memory without granting private tool access.
- **Manifest:** Change Truth's visible presentation/persona without erasing identity continuity.
- **Council:** Multi-character conversation (`POST /v1/companion/council`) where contrasting fictional or advisory viewpoints are evaluated by Truth against objective evidence.

### Replaceable Execution System & Autonomous Improvement
No single model or framework defines JaegerAI. The execution stack combines nine replaceable components (**Models**, **Tools / computer-use**, **Execution engine**, **Memory & state**, **Decision layer**, **Orchestration**, **Permissions**, **Evaluation**, **Scheduler / events**), targeting human-equivalent digital agency and evidence-gated self-improvement (aspirational ≥1%/day measurable progress once capability baselines are established).

---

## 4. Truthful Implementation Status (Verified 2026-11-19)

| Capability | Status | Code & Verification Basis |
|---|---|---|
| **Default Truth identity + epistemic prompt invariant** | **Implemented & verified** | `core/entity/identity.py`, `core/prompt_identity.py`, `features/personality/characters/truth/` (`entity_identity.json` persists across restart; 21 character packs). |
| **Epistemic knowledge store, evidence, contradictions & verification** | **Implemented & verified** | `core/world/model.py`, `core/world/store.py`, `core/gateway/entity_memory.py` (`/v1/runtime/memory/contradictions`, `/claims/{id}/verify`, atomic `/correct`/`/forget`/`/restore`). |
| **Human Needs & Flourishing engine + export** | **Implemented & verified** | `features/human_needs/` (`policy.py`, `store.py`, `routes.py`; quiet-hour/non-intrusive guardrails + `/v1/human-needs/*` persisted across restart). |
| **Companion streaming chat, full memory persistence & Council** | **Implemented & verified** | `features/personality/companion.py`, `core/gateway/character_routes.py` (`/v1/companion/{id}/chat/stream` SSE with interruption, `/v1/companion/council` with Truth synthesis, `operator_state_root()` isolation). |
| **Model routing, full context limits & Mac load protection** | **Implemented & verified** | `core/models/external_model.py`, `core/models/request_policy.py`, `core/gateway/webapp/resource_manager.py` (no artificial 16K/32K cap; `qwen3.5:9b` passed isolated `bugfix_slug`; `mistral-large-4:cloud` passed `bugfix_slug` + `multi_file_rename`). |
| **Authority kernel at tool boundaries** | **Implemented & verified** | `core/authority/kernel.py` (fail-closed `ALLOW`/`DENY`/`MODIFY`/`REQUIRE_APPROVAL`; owner-only identity/memory write gates). |
| **Full-duplex voice, barge-in & live camera exchange** | **Partial — needs end-to-end runtime proof** | Voice/STT/TTS/multimodal modules exist (`packages/jaeger-kokoro-tts`, `jaeger-whisper-stt`, `features/voice`); 10-turn voice + barge-in + live camera demo not yet verified end-to-end. |
| **Living speech-synchronized animated avatars** | **Partial** | `interfaces/ui/src/scenes/CharacterScene.tsx` and `avatar/` exist; live speech/viseme/expression sync with streaming companion & Council not yet connected. |
| **Human-equivalent desktop computer-use** | **Partial — gap** | Playwright browser tool exists (`jaeger_agent/tools/browser.py`); desktop screen control via `CuaDriver` is blocked in `app_control/service.py` (403) and lacks a unified native GUI loop. |
| **Closed-loop autonomous self-improvement pipeline** | **Planned** | Bench harness and skill scoring exist; automated worktree-based propose → test → evaluate → retain/revert loop and daily progress metric are not yet built. |
| **Physical robotics & inter-user assistant federation** | **Planned** | Future phases after digital companion reliability is proven. |

---

## 5. Runtime Protection Rule

The existing repository is the starting implementation; legacy structure and incomplete features do not constrain the target architecture. **The dedicated Mac Studio runtime remains protected from development modifications, restarts, or deployments without separate authorization.**
