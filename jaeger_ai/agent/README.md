# agent/ — framework-free agent layer

> **Modification tier: C — Framework core.** This is the agent's
> runtime: the format → call → parse → dispatch loop, the adapters
> (Anthropic / OpenAI / HermesXML / LocalLlama / MLX), the tool
> registry, the toolsets, the drift parser, the schema sanitiser, the
> retry utils, the callbacks. Edits here change how the agent itself
> runs. Read first, plan minimal patches, run the test suite, and let
> the entry land in `<instance>/audit/self_modification.jsonl`. Full
> policy: [`/docs/SELF_MODIFICATION_BOUNDARIES.md`](../../../docs/SELF_MODIFICATION_BOUNDARIES.md).

## What's in here

Organised by subfolder (the top-level `.py` files moved into these
during the `core/ → agent/` reorg):

| Dir / file | Purpose |
|---|---|
| [`loop/`](loop/) | The turn loop: `jaeger_agent.py` (`run_turn` — format → call → parse → dispatch, skip-final, length-retry, halt backstop, stale-call detection), `callbacks.py`, `interrupt.py`, `loop_backstop.py`, `runtime_bridge.py` (picks the adapter for a JROS client), `agent_core.py` (the chassis `[core]` role). |
| [`adapters/`](adapters/) | One file per backend: `anthropic`, `openai`, `hermes_xml`, `local_llama`, `mlx`. All implement the `ProviderAdapter` ABC in [`adapters/base.py`](adapters/base.py). |
| [`schemas/`](schemas/) | Type homes: `tool_registry.py` (process-wide `name → ToolDef` map), `tool_schema.py` (`ToolDef` + three on-wire renderers), `toolsets.py` (`JAEGER_TOOLSETS` + `resolve_toolsets`), `message_types.py` (internal OpenAI-shaped `Message`/`ToolCall`). |
| [`dialects/`](dialects/) | The drift parser — recovers `<tool_call>` blocks Gemma/Qwen emit as plain text (Gemma brace/paren args, Qwen XML, Hermes JSON envelope). |
| [`parsing/`](parsing/) | `arg_coercion.py` (`"5"` → `5`, bare scalar → `[scalar]`) + `schema_sanitizer.py` (strips JSON-Schema shapes llama-cpp's grammar chokes on). |
| [`prompts/`](prompts/) | System-prompt assembly: `assemble.py` (the `PROMPT_FRAGMENTS` registry + `assemble_prompt`/`iter_fragments`), `context_blocks.py` (dynamic blocks), `framework_agent.md` + `three_laws.md` + `agent_system_prompt.md` (the prompt docs), `rules.py` (the two dynamic toolset notes), `prompts.py` (`build_system_prompt` entry). See `jaeger prompt`. |
| [`safety.py`](safety.py) | Agent-side safety — the Three Laws contract (`prompts/three_laws.md`) the brain reads + the LLM-as-judge `safety_review`. The deterministic pillars (permission gating, audit log) stay in `core/safety/`. |
| [`skill_registry/`](skill_registry/) | The skill loader / manifest / curator + toolset scoping (`CORE`, `TOOLSETS`, `tool_visible`). |
| [`skills/`](skills/) | The curated skill-bundle library (versioned `SKILL.md` folders). |
| [`background/`](background/) | Autonomous / background work: `board.py` (kanban), `cron_runner.py`, `deep_think.py` (skill-dev mode), `processes.py`, `thinking_runner.py` (the opt-in `--think` CoT sidecar). |
| [`personas/`](personas/) | Persona prefill defaults for the setup wizard (NOT read at turn time). |
| [`util/`](util/) | `context_guard.py` (context-window guard), `retry_utils.py` (cloud-adapter backoff). |

## Phase notes

Phase 9 removed pydantic-ai entirely — nothing here imports the old
framework any more. Adapters speak the SDK directly.
