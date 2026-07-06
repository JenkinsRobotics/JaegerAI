# Pipelines — reference docs

Architecture references for JROS's core agent pipelines, so they can be found and
reasoned about later. These describe how things **work today** (verified against
the code, with file pointers) — distinct from the *backlog* of planned changes.

| Pipeline | Doc | In one line |
|----------|-----|-------------|
| Agent turn loop | [agent_turn_pipeline.md](agent_turn_pipeline.md) | `ChatMessage` → `JaegerAgent.run_turn` format→call→parse→dispatch loop → `ChatReply`; `/sense/tool·activity·agent_state` events. |
| Skill / tool discovery | [skill_discovery_pipeline.md](skill_discovery_pipeline.md) | Pull-based: lean hint every turn → full enriched `skill(list)` in research → tier/fallback routing → `skill(view)` recipe. |
| Skill self-improvement | [skill_self_improvement_pipeline.md](skill_self_improvement_pipeline.md) | New version → smoke gate → scored benchmark → keep-better / rollback (curator). |
| Persona | [persona_pipeline.md](persona_pipeline.md) | character.yaml → short brief (identity · traits · soul) → `build_system_prompt`; live reload via the active-character signature. |
| Model / inference | [model_inference_pipeline.md](model_inference_pipeline.md) | model_path → `make_client` → `resolve_engine` (llama.cpp/MLX by format) → `resolve_model_path` → prewarm; external LM Studio/OpenAI/Anthropic path. |
| Voice | [voice_pipeline.md](voice_pipeline.md) | mic → Whisper STT (wake + VAD) → brain → Kokoro TTS → speaker, over the bus, with barge-in / follow-up / self-speech filter. |
| Transport / bus | [transport_pipeline.md](transport_pipeline.md) | pub/sub/request over in-proc queue vs ZMQ XSUB/XPUB broker; msgspec topics; `make_bus_bridge` bus→Qt hop. (Multiprocess path dormant.) |
| Permissions / safety | [permissions_pipeline.md](permissions_pipeline.md) | 6-tier `@requires_tier` → `PermissionPolicy.check`; modes NORMAL/READ_ONLY/PAUSED; per-skill grants; credentials + e-stop hard gates. |
| Memory | [memory_pipeline.md](memory_pipeline.md) | Two-layer SQLite: curated `facts` + episodic turns with sentence-transformers semantic `search_memory`. |

Not yet documented here (add as needed): the Swift↔`jaeger bridge` UI seam
(`jaeger_os/interfaces/swift/PARITY_PLAN.md` covers it), hardware/JP01.

> Some docs carry honest "declared but not the live path" caveats (e.g. `/act/audio_out`
> producer, sqlite-vec KNN, the multiprocess bus) — verified gaps, not omissions.

**Backlog (planned changes, not how-it-works):**
`dev/docs/agentic_skill_pipeline_backlog.md`.

Convention: a pipeline doc is a *map* — accurate, cited, and updated when the code
changes. If a claim can't be verified in the code, it doesn't go in.
