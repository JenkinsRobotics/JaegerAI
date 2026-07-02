# Pipeline: Agent Turn Loop

**What it is:** how one user message becomes one agent reply — the
`format → call → parse → dispatch` loop that drives a `ChatMessage` to a
`ChatReply`, dispatches tool calls and feeds results back, and publishes
live activity/tool/state events on the bus.

## The flow

```
ChatMessage (/act/chat) or Transcript (/sense/transcript)
        │   AgentBridge._on_chat / _on_transcript → inbox queue
        │   (if a turn is live: steer() the running turn instead)
        ▼
AgentBridge._loop  (worker thread)              ← agent/loop/bridge.py
  publish AgentState state="thinking" (/sense/agent_state)
        │
   run_for_voice → _run_turn → _run_turn_via_jaeger_agent   ← jaeger_os/main.py
        │  • one JaegerAgent cached per session key (_jaeger_agents_by_session)
        │  • first build: build_system_prompt + build_jaeger_agent
        │  • every turn: _refresh_character_prompt (persona hot-reload)
        │  • serialize on _pipeline['llm_lock']
        ▼
   drive_one_turn(agent, user_text)             ← agent/loop/runtime_bridge.py
        │
   JaegerAgent.run_turn(user_message)           ← agent/loop/jaeger_agent.py
     append {role:"user"}; then loop up to max_iterations (24):
        │
   ┌─▶ 1-3  _one_model_step: format_messages → adapter.call → parse_response
   │         (pre-flight ContextGuard trim; classified retry + fallback chain;
   │          heartbeat ticks fire on_heartbeat)
   │    4   append assistant Message (may hold text AND tool_calls)
   │        no tool_calls → return text  ── final answer ──▶
   │    5a  skip-final: iter 1, one deterministic tool, non-multistep
   │        → dispatch + finalizer, return (no 2nd model call)
   │    6   dispatch each tool_call → append {role:"tool"} result
   │         (all-read/path-scoped batch → _dispatch_parallel)
   │         on_tool_progress start/done · on_tool_done audit
   │         loop-backstop check (identical-call / semantic-failure / runaway)
   └───────── loop ◀──────────────────────────────────────────┘
        │
   answer text ─▶ drive_one_turn returns {answer, tool_activity,
                  first_decision, iterations, halt_reason, …}
        ▼
   AgentBridge publishes ChatReply(text, session)  (/sense/chat)
   publish AgentState state="idle"

  mid-turn, via callbacks → _BusEventAdapter:
     tool.progress  → ToolEvent      (/sense/tool)
     agent.activity → AgentActivity  (/sense/activity)
```

## Key files / functions

- `agent/loop/jaeger_agent.py :: JaegerAgent.run_turn` — the public turn
  entry. Clears per-turn state, appends the user message, calls
  `_run_turn_inner`, and repairs the transcript on every exit path
  (pre-flight `ContextOverflow` rolls the user message back and re-raises;
  mid-turn overflow / interrupt / error close dangling tool calls so the
  next turn formats cleanly).
- `JaegerAgent._run_turn_inner` — the loop body. Steps 1-6 in the docstring
  (`run_turn`): format→call→parse (`_one_model_step_with_length_retry`),
  append assistant, return on no-tool-calls, else dispatch. Skip-final
  short-circuit at iteration 1 (`_finalize_skip_final`). Falls out of the
  for-loop → `_wind_down_summary` (one toolless grace call).
- `JaegerAgent._one_model_step` — `adapter.format_messages(messages, tools,
  system_prompt)` → `adapter.call(...)` → `adapter.parse_response(raw)`.
  Pre-flight `ContextGuard.trim_to_fit`; classified retry (rate_limit /
  transient) then fallback-adapter chain; `_accumulate_usage` for token
  counts.
- `JaegerAgent._dispatch_one_tool` = `_prepare_dispatch` → `_execute_prepared`
  → `_finish_dispatch`. `_execute_prepared` calls `tool_def.dispatch(args)`;
  exceptions become `{"ok": False, "error_type": ...}` result dicts (a tool
  crash never kills the loop). `_finish_dispatch` appends the
  `{role:"tool", tool_call_id, name, content}` result and fires
  `on_tool_progress("done")` + `on_tool_done`.
- `JaegerAgent._dispatch_parallel` / `_batch_is_parallel_safe` — all-read or
  non-overlapping path-scoped file batches (>1 call) run on a
  `ThreadPoolExecutor`; prepare/finish stay serial and in batch order.
- Tool-call dedupe: identical `side_effect="read"` calls within one batch
  return a `duplicate_of` marker instead of re-dispatching.
- `agent/loop/callbacks.py :: AgentCallbacks` — the observability seam
  (`tool_progress`, `thinking`, `tool_done`, `heartbeat`, `step`,
  `before_tool_call`, `after_tool_call`, `interrupt`, `stream_delta`). Each
  invoked via an `on_*` wrapper that swallows handler exceptions.
- `agent/loop/runtime_bridge.py :: drive_one_turn` — calls
  `agent.run_turn`, returns the latency-log dict (`answer`, `tool_activity`,
  `first_decision`, `elapsed_s`, `skipped`, `halt_reason`, `iterations`,
  `new_messages`, token counts). Per-turn slice comes from
  `agent.last_turn_messages` (stable across mid-turn context trims).
- `agent/loop/runtime_bridge.py :: build_jaeger_agent` — selects the adapter
  from the client (`_adapter_for_client`: local llama / MLX / anthropic /
  openai-compat), installs the `ContextGuard`, `skip_final_finalizer`
  (bounded paraphrase via `main._fast_finalize_sync`), and callbacks.

### ChatMessage → ChatReply (the bus seam)

- `jaeger_os/core/messages.py` — the bus vocabulary. `ChatMessage`
  (`/act/chat`, operator→agent), `ChatReply` (`/sense/chat`, agent→surfaces,
  Tier-1: only the agent publishes it), `Transcript` (`/sense/transcript`,
  STT), plus `ToolEvent` (`/sense/tool`), `AgentActivity` (`/sense/activity`),
  `AgentState` (`/sense/agent_state`). Every message carries `session` so a
  surface renders only its own conversation.
- `agent/loop/bridge.py :: AgentBridge` — subscribes `ChatMessage.topic` /
  `Transcript.topic`, runs each turn on its own worker thread through
  `run_for_voice`, and publishes `ChatReply` + `AgentState`. A live turn
  redirects a follow-up message via `_steer_active_turn` (the agent's
  `steer()`) instead of queuing. Never imports the agent directly — only the
  bus vocabulary.
- `agent/loop/bridge.py :: _BusEventAdapter` — installed as
  `_pipeline['event_bus']`; maps the loop's `tool.progress` →
  `ToolEvent(/sense/tool)` and `agent.activity` →
  `AgentActivity(/sense/activity)`, tagged with the current session.

### The turn glue (main.py)

- `jaeger_os/main.py :: run_for_voice` — thin adapter over `_run_turn`;
  persists the user+assistant turn to the session store. `_run_turn` wraps
  `_run_turn_via_jaeger_agent`.
- `jaeger_os/main.py :: _run_turn_via_jaeger_agent` — caches one
  `JaegerAgent` per session key, builds the `AgentCallbacks` that forward to
  `_pipeline['event_bus']` (`tool.progress` / `agent.activity`) and to the
  memory audit (`_tool_done` → `mem.record_tool_call` + `trace.trace_step`),
  sets `_pipeline['active_jaeger_agent']`, runs under `llm_lock`, and calls
  `drive_one_turn`.
- `jaeger_os/main.py :: _refresh_character_prompt` — rebuilds the system
  prompt via `build_system_prompt` when `active_character_signature` changed
  since the last build, so a persona swap takes effect the same turn (no
  restart). Rebuilds only on an actual change.

### System prompt per turn

- `agent/prompts/prompts.py :: build_system_prompt(layout)` →
  `assemble_prompt(layout, mode="agent")`.
- `agent/prompts/assemble.py :: PROMPT_FRAGMENTS` — the declared registry;
  list order **is** the prompt order. For `mode="agent"`: `three_laws`,
  `identity`, `soul`, `personality`, `framework`, `skill_index`,
  `v2_contract`, `runtime_tail`, `board_digest`, `tool_catalog`. Each
  fragment declares which modes include it; `iter_fragments` renders the
  applicable ones and a broken fragment yields "" rather than crashing boot.
- The lean skill-index hint is the `skill_index` fragment →
  `context_blocks.build_skill_index_block()` (skipped for sub-agents). See
  the skill-discovery pipeline doc for what it contains.
- Session prompt = base prompt + a frozen facts snapshot
  (`_facts_snapshot_block`), frozen at agent construction for prefix-cache
  stability.

### Tools exposed to the model

- `agent/schemas/tool_registry.py :: get_tools()` — snapshot of every
  registered `ToolDef` in insertion order.
- `JaegerAgent` tool selection precedence (`__init__`): explicit
  `tools=[...]` allowlist → `toolsets={...}` (resolved via
  `tool_bundles.resolve_toolsets`) → else the full registry. `beta` tools are
  excluded outside dev mode (`_exclude_beta`). The dispatch map
  (`_dispatch_by_name`) is built from this set so a model can only dispatch
  the agent's intended tools.
- `JaegerAgent.tools` (property) filters `_all_tools` through
  `toolset_scoping.tool_visible` on every access, so a mid-session
  `load_toolset` changes what the model sees next turn without rebuilding
  the agent. `_refresh_tool_catalog` (top of every turn) picks up tools
  registered mid-session. `tool_visible` fails **open**: scoping off → all
  visible; a tool in no toolset is never hidden.

## Status

- **Verified against code** (2026-07-01, branch 0.6.0): loop steps,
  skip-final, parallel/serial dispatch, dedupe, transcript-repair exit
  paths, callback→bus event mapping, prompt fragment order, tool
  visibility/scoping.
- The loop lives behind a migration bridge (`runtime_bridge.py`,
  "migration-only … collapses into `main.py` when pydantic-ai is gone");
  `jaeger_agent_enabled()` reads `JAEGER_USE_NEW_AGENT`. This doc describes
  the `JaegerAgent` path, which is what `_run_turn_via_jaeger_agent` /
  `AgentBridge` drive.
