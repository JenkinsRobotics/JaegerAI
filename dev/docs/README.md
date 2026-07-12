# dev/docs — index

`dev/docs` reads as one narrative: **Reality** (what runs today), **History**
(the append-only log of how it got here), **Roadmap** (what's next), and
**Vision** (where this goes long-term). Engineering docs stay grouped by
area below that. Nothing here is deleted when it goes stale — it moves to
`history/`.

---

## Reality — the system as it exists

Live description of what's running right now. If code and doc disagree, the
code wins and the doc is out of date — fix the doc, don't trust it blind.

| doc | summary |
|---|---|
| [system_runtime_user.md](reality/system_runtime_user.md) | Framework-vs-operator-state boundary — where every persistent file belongs |
| [STATUS.md](reality/STATUS.md) | Pipeline runtime-verification status, updated every behavior-touching commit |
| [STRUCTURE.md](reality/STRUCTURE.md) | Repository structure guide for reviewers / new contributors |
| [naming_conventions.md](reality/naming_conventions.md) | Tools / skills / repo naming conventions |
| [agentic_runners.md](reality/agentic_runners.md) | The two-tier agentic runner design (realtime + Deep Think) + inference lanes |
| [memory_architecture.md](reality/memory_architecture.md) | Subject-attributed SQL memory — curated facts + episodic history |
| [persona_compiler.md](reality/persona_compiler.md) | Persona compiler — State/View split for the character layer |
| [skill_standard.md](reality/skill_standard.md) | The self-authored skill standard — cheat sheets for a 4B agent |
| [pipeline_health.md](reality/pipeline_health.md) | What's solid / incomplete / unwired across the core pipelines |
| [scenario_bench.md](reality/scenario_bench.md) | The two JROS benchmarks — routing corpus vs. scenario suite |
| [scenario_test_suite.md](reality/scenario_test_suite.md) | The full-system, real-world scenario test suite (81-case corpus) |

**Also live reference:** [`pipelines/`](pipelines/) — one doc per core pipeline
(agent turn loop, skill discovery, memory, persona, voice, transport,
permissions, model inference), each verified against code.

## History — the log

Append-only. Shipped plans, closed roadmaps, past reviews, retrospectives —
kept for the record, never rewritten.

| doc | summary |
|---|---|
| [HISTORY.md](history/HISTORY.md) | Release-by-release development history |
| [ROADMAP_0.2.0.md](history/ROADMAP_0.2.0.md) | 0.2.0 roadmap (shipped) |
| [ROADMAP_0.4.md](history/ROADMAP_0.4.md) | 0.4 roadmap — embodied node architecture (shipped) |
| [ROADMAP_0.5.md](history/ROADMAP_0.5.md) | 0.5 roadmap — animation / personality / skill tree / streaming (shipped) |
| [ROADMAP_0.6.md](history/ROADMAP_0.6.md) | 0.6 roadmap — install / update / lifecycle UX (shipped) |
| [BENCHMARK_0.1.0.md](history/BENCHMARK_0.1.0.md) | 0.1.0 full verification benchmark |
| [0.4.0_pre_main_benchmark.md](history/0.4.0_pre_main_benchmark.md) | 0.4.0 pre-main benchmark runbook |
| [0.4.0_code_review_prompt.md](history/0.4.0_code_review_prompt.md) | 0.4.0 code review request prompt |
| [0.5.0_walk_the_flow.md](history/0.5.0_walk_the_flow.md) | 0.5.0 ship-gate operator verification walkthrough |
| [code_review_2026_05_24.md](history/code_review_2026_05_24.md) | 2026-05-24 external code review — dispositions |
| [code_review_prompt.md](history/code_review_prompt.md) | Standing code-review prompt for the agentic pipeline |
| [odysseus_review_and_0.3.0_plan.md](history/odysseus_review_and_0.3.0_plan.md) | Odysseus project review + 0.3.0 game plan |
| [hermes_cui_port.md](history/hermes_cui_port.md) | Hermes CLI/CUI → JROS TUI feature-inventory + port checklist |
| [hermes_internals_audit.md](history/hermes_internals_audit.md) | Hermes vs. JROS internals port audit (non-tool/non-skill) |
| [hermes_tool_parity.md](history/hermes_tool_parity.md) | Tool parity audit — Jaeger-OS vs. Hermes Agent |
| [hermes_tool_skill_audit.md](history/hermes_tool_skill_audit.md) | Hermes vs. JROS tool & skill integration audit |
| [tui_port_notes.md](history/tui_port_notes.md) | TUI port — Hermes feature parity notes |
| [SKILL_EVOLUTION_PLAN.md](history/SKILL_EVOLUTION_PLAN.md) | Skill self-improvement plan — base loop shipped in 0.6 |
| [skill-evolution-impl-A-signal-trigger.md](history/skill-evolution-impl-A-signal-trigger.md) | Skill evolution plan A — signal + trigger (implemented) |
| [skill-evolution-impl-B-review.md](history/skill-evolution-impl-B-review.md) | Skill evolution plan B — the review (implemented) |
| [skill-evolution-impl-C-lifecycle.md](history/skill-evolution-impl-C-lifecycle.md) | Skill evolution plan C — archive/scoring/retirement (implemented) |
| [skill_unification.md](history/skill_unification.md) | Skill unification — one Skill, one loader (DONE, presence-based, 2026-07-02) |
| [skill_schema_v3-v1.md](history/skill_schema_v3-v1.md) | Earlier top-level skill-manifest v3 note — the code-verified spec `skill_loader.py` actually implements; diverges from the larger aspirational draft at [skills/skill_schema_v3.md](skills/skill_schema_v3.md), kept for the record rather than reconciled |
| [SWIFT_APP_ARCHITECTURE_PLAN.md](history/SWIFT_APP_ARCHITECTURE_PLAN.md) | Swift-first app architecture plan (shipped 0.6/0.7) |
| [JROS_0.8_MODULE_REFACTOR_SPEC.md](history/JROS_0.8_MODULE_REFACTOR_SPEC.md) | 0.8 runtime-unification + node-modules spec — Phase U/M shipped; hardware-modules step still open, see the Roadmap section below |
| [JROS_0.8_U1_BUS_UNIFICATION_PLAN.md](history/JROS_0.8_U1_BUS_UNIFICATION_PLAN.md) | 0.8 U1 — bus unification (shipped) |
| [JROS_0.8_U3_SUPERVISION_PLAN.md](history/JROS_0.8_U3_SUPERVISION_PLAN.md) | 0.8 U3 — one runtime, supervisor-owned nodes (shipped) |
| [JROS_0.8_M1_KOKORO_TTS_PLAN.md](history/JROS_0.8_M1_KOKORO_TTS_PLAN.md) | 0.8 M1 — kokoro_tts, the first engine-module (shipped) |
| [JROS_0.8_M2a_SLOT_RESOLUTION_PLAN.md](history/JROS_0.8_M2a_SLOT_RESOLUTION_PLAN.md) | 0.8 M2a — slot resolution + graceful module removal (shipped) |
| [JROS_0.8_M2b_WHISPER_STT_PLAN.md](history/JROS_0.8_M2b_WHISPER_STT_PLAN.md) | 0.8 M2b — whisper_stt, the second engine-module (shipped) |
| [JROS_0.8_M2c_ANIMATION_MEDIA_PLAN.md](history/JROS_0.8_M2c_ANIMATION_MEDIA_PLAN.md) | 0.8 M2c — animation + media modules (shipped) |
| [JROS_0.8_M3_PLUGINS_PLAN.md](history/JROS_0.8_M3_PLUGINS_PLAN.md) | 0.8 M3 — plugins family graduation/gating (shipped) |
| [scenario_results_2026-07-06.md](history/scenario_results_2026-07-06.md) | Scenario suite live-run results (2026-07-06) |
| [session_retrospective_2026_07.md](history/session_retrospective_2026_07.md) | Retrospective — persona + skill/tool scaling work (2026-07-02/03) |
| [framework_review/](history/framework_review/) | JROS Framework Review — 0.6 alpha architecture/library review |
| [mochi_animation_docs/](history/mochi_animation_docs/) | Mochi-era animation/avatar docs (asset conventions, learn/, gameplan) |

## Roadmap — what's next

Open future work, not yet shipped.

| doc | summary |
|---|---|
| [future_backlog.md](roadmap/future_backlog.md) | Living backlog of deferred work — the "later" pile |
| [agentic_skill_pipeline_backlog.md](roadmap/agentic_skill_pipeline_backlog.md) | Tools ↔ tool-skills ↔ playbook-skills routing improvement backlog |
| [JROS_0.8_CAPABILITY_LAYER_DESIGN.md](roadmap/JROS_0.8_CAPABILITY_LAYER_DESIGN.md) | 0.8 Mind↔Body capability-layer design draft — pending operator approval |

Also open: the hardware-modules step of [JROS_0.8_MODULE_REFACTOR_SPEC.md](history/JROS_0.8_MODULE_REFACTOR_SPEC.md)
(Phase U/M shipped; hardware modules not yet converted).

## Vision — where this goes

Grounded long-term direction — the lens for major structural work, not a
spec to build against today. Canonical home is **JaegerOS**, not this
repo (0.9 step 4 split): [`JaegerOS/dev/docs/vision/`](https://github.com/Jenkins-Robotics/JaegerOS/tree/master/dev/docs/vision)
— `THREE_TIER_STRUCTURE.md` (the Mind/Body/Soul model + split triggers),
`framework_vision.md` (the modular north star), and
`JAEGER_ECOSYSTEM.md` (the four-repo picture this split produced).
Linked, not duplicated — read them there for the full reasoning.

---

## Engineering areas

Docs grouped by area — active + closed design docs live side by side; status
is per-doc, not per-folder.

| folder | covers |
|---|---|
| [core/](core/) | Agent loop · prompts · memory · tools · models · instance |
| [audio/](audio/) | STT · TTS · voice pipeline |
| [avatar/](avatar/) | Animation · media · Studio/GUI · characters |
| [hardware/](hardware/) | JP01 · motor/light/vision · device adapters |
| [infra/](infra/) | Transport/bus · app framework · protocol · client · deploy |
| [skills/](skills/) | Skill tree · sharing · marketplace · schema · templates |
| [pipelines/](pipelines/) | Live reference docs for the core agent pipelines (see Reality above) |
| [revision_summaries/](revision_summaries/) | Per-release write-ups (0.1.0 → 0.7.0) |
| [archive/](archive/) | Deferred/shelved planning briefs, kept for the record |
| [library_review/](library_review/) | Upstream-project (Hermes, VoiceLLM, JP01, Mochi) value reviews |
| [skill_template/](skill_template/) | Starter template for authoring a new code skill |

Pipeline diagrams live in [`../infographic/`](../infographic/).
