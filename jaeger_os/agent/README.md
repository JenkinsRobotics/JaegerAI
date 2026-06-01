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

| File / dir | Purpose |
|---|---|
| [`jaeger_agent.py`](jaeger_agent.py) | The loop. `run_turn` drives format → call → parse → dispatch with skip-final, length-retry, halt backstop, stale-call detection. |
| [`adapters/`](adapters/) | One file per backend: `anthropic`, `openai`, `hermes_xml`, `local_llama`, `mlx`. All implement the `ProviderAdapter` ABC defined in [`adapters/base.py`](adapters/base.py). |
| [`tool_registry.py`](tool_registry.py) | Process-wide `name → ToolDef` map. `@register_tool` decorator + `register_tool_instance` runtime path. |
| [`tool_schema.py`](tool_schema.py) | `ToolDef` — one tool, three on-wire renderers (Anthropic / OpenAI / Hermes-XML), Pydantic-validated dispatch. |
| [`toolsets.py`](toolsets.py) | Hermes-style toolset groups + the `resolve_toolsets` resolver. Lets a session expose only `default` / `essentials` / `robot` / etc. instead of all ~80 tools. |
| [`drift_parser.py`](drift_parser.py) | Recovers `<tool_call>` blocks Gemma/Qwen emit as plain text. Three dialects: Gemma brace args, Gemma paren kwargs, Qwen XML, plus the Hermes JSON envelope. |
| [`arg_coercion.py`](arg_coercion.py) | Pre-validation coercion: `"5"` → `5`, bare scalar → `[scalar]` when schema expects array. Catches the common open-weight-model arg-drift cases. |
| [`schema_sanitizer.py`](schema_sanitizer.py) | Strips JSON-Schema shapes llama-cpp's grammar generator chokes on. |
| [`callbacks.py`](callbacks.py) | `AgentCallbacks` — observation hooks the loop fires (tool_progress, step, heartbeat, before/after_tool_call). |
| [`interrupt.py`](interrupt.py) | `interruptible_call` + `StaleCallTimeout`. Daemon-thread pattern with cancel-event polling. |
| [`loop_backstop.py`](loop_backstop.py) | The three counters that guarantee a turn terminates: identical-call, semantic-failure, runaway-total. |
| [`retry_utils.py`](retry_utils.py) | `jittered_backoff` + `retry_with_backoff`. For cloud-adapter transient-error retries. |
| [`runtime_bridge.py`](runtime_bridge.py) | `build_jaeger_agent(client, ...)` — picks the right adapter from a JROS client and constructs a configured `JaegerAgent`. Used by `main.py`'s turn entry. |
| [`message_types.py`](message_types.py) | The internal `Message` + `ToolCall` TypedDicts. OpenAI-shaped; adapters translate to/from this. |
| [`prompt_builder.py`](prompt_builder.py) | Phase-1 stub for system-prompt assembly. Defers to `core/prompts.py` today. |

## Phase notes

The agent layer was built in Phases 1-9 (see `/docs/agent_refactor_phase_*.md`).
Phase 9 removed pydantic-ai entirely — nothing here imports the old
framework any more. Adapters speak the SDK directly.
