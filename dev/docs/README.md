# dev/docs — by area

Development docs grouped by **area** so a section can be handed to a dev and
they get everything for it in one folder. Status is a column, not a folder (a
doc's area is stable; its status changes). Release history is in
[HISTORY.md](HISTORY.md).

**Status:** 🟢 open (active / planned / live reference) · ⚪ closed (shipped,
done, or a historical artifact — kept for reference).

**Other folders:** [`revision_summaries/`](revision_summaries/) (per-release
notes) · [`architecture/`](architecture/) · [`library_review/`](library_review/)
(upstream-project ports) · [`archive/`](archive/) · [`skill_template/`](skill_template/).
Pipeline diagrams live in [`../infographic/`](../infographic/).

---

## core — agent loop · prompts · memory · tools · models · instance
| doc | status | summary |
|---|---|---|
| [agent_contract.md](core/agent_contract.md) | 🟢 | agent system-prompt rules contract |
| [lean_surface.md](core/lean_surface.md) | 🟢 | lean tool surface — pull-not-push |
| [context_guard.md](core/context_guard.md) | 🟢 | context-window guardrail layer |
| [deep_think_design.md](core/deep_think_design.md) | 🟢 | sleep-cycle awake/asleep modes |
| [external_models.md](core/external_models.md) | 🟢 | external-model opt-in pipeline |
| [REVIEW_BRIEF_AGENT.md](core/REVIEW_BRIEF_AGENT.md) | 🟢 | agent-loop review brief for reviewers |
| [SELF_MODIFICATION_BOUNDARIES.md](core/SELF_MODIFICATION_BOUNDARIES.md) | 🟢 | agent self-modification filesystem limits |
| [main_loop_review.md](core/main_loop_review.md) | ⚪ | main-loop architecture review + rebuild |
| [agent_refactor_phase_0.md](core/agent_refactor_phase_0.md) | ⚪ | pydantic-ai → JaegerAgent audit |
| [agent_refactor_phase_6.md](core/agent_refactor_phase_6.md) | ⚪ | partial migration behind a flag |
| [agent_refactor_phase_7.md](core/agent_refactor_phase_7.md) | ⚪ | Hermes-style toolsets |
| [agent_refactor_phase_8.md](core/agent_refactor_phase_8.md) | ⚪ | resilience adoptions |
| [agent_refactor_phase_9.md](core/agent_refactor_phase_9.md) | ⚪ | app review + cleanup |
| [0.5.0_agent_reorg_plan.md](core/0.5.0_agent_reorg_plan.md) | ⚪ | agent-folder reorg (done) |
| [toolset_scoping_ab.md](core/toolset_scoping_ab.md) | ⚪ | toolset scoping A/B bench |
| [native_handler_ab.md](core/native_handler_ab.md) | ⚪ | native chat-handler A/B bench |
| [kanban_design.md](core/kanban_design.md) | ⚪ | kanban board (shipped 0.1.0) |
| [physical_skills_status.md](core/physical_skills_status.md) | ⚪ | physical-skills scaffolding status |

## audio — STT · TTS · voice
| doc | status | summary |
|---|---|---|
| [0.4_audio_node_realtime_plan.md](audio/0.4_audio_node_realtime_plan.md) | ⚪ | realtime audio/node hardening plan |
| [0.4.0_audio_refactor_prompt.md](audio/0.4.0_audio_refactor_prompt.md) | ⚪ | 0.4.0 audio refactor scope |
| [0.4.0_voice_gate_unification_prompt.md](audio/0.4.0_voice_gate_unification_prompt.md) | ⚪ | voice-gate unification + TUI split |
| [0.4.0_voice_gating_review.md](audio/0.4.0_voice_gating_review.md) | ⚪ | VoiceLLM vs JROS gating analysis |
| [0.4.0_review_patch_prompt.md](audio/0.4.0_review_patch_prompt.md) | ⚪ | 0.4.0 review-findings patch |

> Active audio work now lives in code (`plugins/whisper_stt/` method layer,
> `nodes/kokoro_tts`, `core/audio`) + [`../infographic/voice_in_asr.md`](../infographic/voice_in_asr.md)
> · [`stt_llm_tts.md`](../infographic/stt_llm_tts.md). These docs are the 0.4.0 history.

## avatar — animation · media · Studio/GUI · characters
| doc | status | summary |
|---|---|---|
| [0.5.0_swift_renderer_plan.md](avatar/0.5.0_swift_renderer_plan.md) | 🟢 | Swift renderer for the avatar |
| [0.5.0_timeline_schema.md](avatar/0.5.0_timeline_schema.md) | 🟢 | multi-track animation timeline schema |
| [0.5_brainstorm.md](avatar/0.5_brainstorm.md) | 🟢 | lightweight face-avatar stack |

## hardware — JP01 · motor/light/vision · device adapters
| doc | status | summary |
|---|---|---|
| [JROS_HARDWARE_FRAMEWORK_PLAN.md](hardware/JROS_HARDWARE_FRAMEWORK_PLAN.md) | 🟢 | hardware integration framework design |
| [JROS_HARDWARE_INTEGRATION_BRIEF.md](hardware/JROS_HARDWARE_INTEGRATION_BRIEF.md) | 🟢 | hardware integration brief |

## infra — transport/bus · app framework · protocol · client · deploy
| doc | status | summary |
|---|---|---|
| [JROS_APP_FRAMEWORK_PLAN.md](infra/JROS_APP_FRAMEWORK_PLAN.md) | 🟢 | unified app-framework design |
| [JROS_APP_FRAMEWORK_BRIEF.md](infra/JROS_APP_FRAMEWORK_BRIEF.md) | 🟢 | app-framework planning brief |
| [JROS_CLIENT_PROTOCOL.md](infra/JROS_CLIENT_PROTOCOL.md) | 🟢 | client wire-protocol spec |
| [instance_layout.md](infra/instance_layout.md) | 🟢 | per-agent instance disk layout |
| [lifecycle_design.md](infra/lifecycle_design.md) | 🟢 | instance lifecycle verbs |
| [remote_access.md](infra/remote_access.md) | 🟢 | remote access for the device |
| [setup.md](infra/setup.md) | 🟢 | setup / upgrade / uninstall |

## skills — skill tree · sharing · marketplace · templates
| doc | status | summary |
|---|---|---|
| [SKILL_TREE.md](skills/SKILL_TREE.md) | 🟢 | XP-driven progression contract |
| [skill_schema_v3.md](skills/skill_schema_v3.md) | 🟢 | unified skill schema v3 |
| [skill_sharing_pipeline.md](skills/skill_sharing_pipeline.md) | 🟢 | skill → framework promotion path |
| [marketplace_spec.md](skills/marketplace_spec.md) | 🟢 | skill marketplace spec |
| [0.5.x_skill_tree_evolution_plan.md](skills/0.5.x_skill_tree_evolution_plan.md) | 🟢 | skill-tree directions for 0.5+ |

## process — roadmaps · status · reviews · audits · plans
| doc | status | summary |
|---|---|---|
| [ROADMAP_0.5.md](process/ROADMAP_0.5.md) | 🟢 | 0.5 roadmap (current) |
| [STATUS.md](process/STATUS.md) | 🟢 | pipeline runtime status |
| [STRUCTURE.md](process/STRUCTURE.md) | 🟢 | repository structure guide |
| [naming_conventions.md](process/naming_conventions.md) | 🟢 | tools/skills/repo naming |
| [ROADMAP_0.2.0.md](process/ROADMAP_0.2.0.md) · [ROADMAP_0.4.md](process/ROADMAP_0.4.md) | ⚪ | shipped roadmaps |
| [BENCHMARK_0.1.0.md](process/BENCHMARK_0.1.0.md) · [0.4.0_pre_main_benchmark.md](process/0.4.0_pre_main_benchmark.md) | ⚪ | release benchmarks |
| [0.5.0_walk_the_flow.md](process/0.5.0_walk_the_flow.md) · [0.4.0_code_review_prompt.md](process/0.4.0_code_review_prompt.md) · [code_review_2026_05_24.md](process/code_review_2026_05_24.md) | ⚪ | ship gates + reviews |
| [hermes_internals_audit.md](process/hermes_internals_audit.md) · [hermes_tool_parity.md](process/hermes_tool_parity.md) · [hermes_tool_skill_audit.md](process/hermes_tool_skill_audit.md) · [hermes_cui_port.md](process/hermes_cui_port.md) · [tui_port_notes.md](process/tui_port_notes.md) | ⚪ | Hermes parity ports |
| [odysseus_review_and_0.3.0_plan.md](process/odysseus_review_and_0.3.0_plan.md) | ⚪ | Odysseus review + 0.3 plan |
