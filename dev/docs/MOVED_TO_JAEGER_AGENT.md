# Agent docs moved to jaeger-agent

0.11.0. Documentation for shipped agent mechanism now lives in the
`jaeger-agent` repo, beside the code it describes:

    jaeger-agent/docs/ARCHITECTURE.md   ← start here
    jaeger-agent/docs/pipelines/        turn loop, memory, permissions,
                                        model inference, skill discovery
                                        + self-improvement
    jaeger-agent/docs/core/             agent contract, context guard,
                                        toolset-scoping A/B, native-handler
                                        A/B, lean surface, main-loop review,
                                        external models, deep think
    jaeger-agent/docs/skills/           skill schema v3, skill standard,
                                        skill sharing, agentic runners

## What deliberately stayed here

Applications are where things are designed, developed and tested; only
what is locked in gets a channel to the agent. So R&D artefacts remain
in this repo:

  - `roadmap/PERSONA_PIPELINE_ABC_DESIGN.md`, `PERSONA_MODE_C_BUILD_PLAN.md`
    — the exploration that produced Persona Mode C. The shipped mechanism
    is documented in jaeger-agent/docs/ARCHITECTURE.md §6; this is the
    reasoning about three modes, two of which were never built.
  - `roadmap/agentic_skill_pipeline_backlog.md` — a backlog is by
    definition not locked in.
  - `skills/SKILL_TREE.md` — no corresponding shipped code.
  - `core/SELF_MODIFICATION_BOUNDARIES.md` — safety policy. Demo-stage,
    still being flushed out; it belongs where it is being worked on.
  - Personas and traits generally. The persona LANE locked in and is
    documented in jaeger-agent (§6), but characters, trait layers and the
    tools that read them are this repo's R&D — jaeger-agent's
    tools/persona.py is six-for-six coupled to this repo precisely
    because that content lives here.
  - `pipelines/persona_pipeline.md` — character → system prompt. Character
    lives in THIS repo (`jaeger_ai/personality/`), so this is app-side.
  - `pipelines/voice_pipeline.md`, `transport_pipeline.md`, everything
    under `audio/` — application concerns.
  - `core/agent_refactor_phase_*.md` — the history of extracting the agent
    FROM this repo. That story belongs to the repo it left.
