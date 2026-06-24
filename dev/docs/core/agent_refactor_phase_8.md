# Phase 8 — Hermes-lift resilience batch

**Status:** Phase 8.1 shipped. Four priority adoptions from the Hermes
upstream review (`agent_refactor_phase_7.md` baseline → 905 tests; this
phase → **987 tests**, +82 new, 0 regressions).

## Why this phase exists

After Phase 6.2 removed pydantic-ai and Phase 7 added Hermes-style
toolsets, the next biggest gaps between JROS and Hermes were in
**resilience to model-output drift** (Priority 1), **graceful handling
of token-limit truncation** (Priority 2), **detection of hung backends**
(Priority 3), and **decorrelated retry policy** (Priority 4). Each one
is a small, mostly-local addition with a measurable production payoff.

## Priority 1 — Argument coercion + schema sanitization

### What landed
| File | Purpose |
|---|---|
| [src/jaeger_os/agent/arg_coercion.py](../src/jaeger_os/agent/arg_coercion.py) | `coerce_args(args, schema)` — best-effort type coercion before Pydantic validation. Ports `python_hermes_agent.upstream.model_tools.coerce_tool_args` |
| [src/jaeger_os/agent/schema_sanitizer.py](../src/jaeger_os/agent/schema_sanitizer.py) | `sanitize_tool_schemas`, `strip_nullable_unions`, `strip_pattern_and_format` — fix schemas that strict backends (llama.cpp grammar, OpenAI Codex, Anthropic input_schema) reject. Ports `python_hermes_agent.upstream.tools.schema_sanitizer` |
| [tests/.../test_arg_coercion.py](../tests/jaeger_os/agent/test_arg_coercion.py) | 27 tests |
| [tests/.../test_schema_sanitizer.py](../tests/jaeger_os/agent/test_schema_sanitizer.py) | 20 tests |

### Wiring
- `ToolDef.dispatch` runs `coerce_args` before `args_model.model_validate` so a Gemma-emitted `{"limit": "5"}` validates as `{"limit": 5}` and the array-wrap case `{"urls": "https://a"}` → `{"urls": ["https://a"]}` works without a schema bug.
- `LocalLlamaAdapter._LlamaChatFacade.create` calls `sanitize_tool_schemas` on the tools list before handing them to `llama.cpp`'s grammar generator — fixes the HTTP 400 "Unable to generate parser" failures on schemas with bare-string types or `anyOf` nullable unions.

### Bench expectation
Open-weight models (Qwen3.5-9B, Gemma 4) routinely emit string-typed scalars where the schema declares numbers — every one of those calls previously failed Pydantic validation and surfaced as a tool error. Coercion converts most into successful calls.

## Priority 2 — Length-continue + truncated tool-call retries

### What landed
| Change | Purpose |
|---|---|
| `Message.finish_reason` field (TypedDict) | Adapters surface the model's stop reason so the loop can detect length-truncation |
| `OpenAIAdapter.parse_response` | Reads `choice.finish_reason` |
| `AnthropicAdapter.parse_response` | Reads `raw.stop_reason`, normalises `"max_tokens"` → `"length"` |
| `JaegerAgent._one_model_step_with_length_retry` | Two-case retry — truncated tool-call (1 silent retry) vs truncated text (up to 3 continuation nudges, stitched) |
| [tests/.../test_length_retry.py](../tests/jaeger_os/agent/test_length_retry.py) | 8 tests |

### Behaviour
1. **Truncated tool-call** (`finish_reason="length"` + non-empty `tool_calls`): retry the same model call ONCE without appending the broken response. Two truncations in a row falls through — the dispatcher surfaces the partial-args error and the next iteration recovers.
2. **Truncated text** (`finish_reason="length"` + no `tool_calls`): append the partial as an assistant turn, inject `"continue from exactly where you stopped — no preamble"` as a user turn, retry. Trim both synthetic turns from history after stitching so the visible transcript carries only the final concatenated message. Up to 3 nudges, then return the accumulated partial.

The retry budgets match Hermes' legacy constants (`_MAX_LENGTH_CONTINUE_RETRIES = 3`, `_MAX_TRUNCATED_TOOL_CALL_RETRIES = 1`) so behaviour is comparable across the two implementations.

## Priority 3 — Stale-call detector + activity heartbeat

### What landed
| Change | Purpose |
|---|---|
| `StaleCallTimeout` exception | Distinct from `AgentInterrupted` — adapter fallback chain can react |
| `interruptible_call(stale_timeout=..., on_heartbeat=...)` | New kwargs; backwards-compatible defaults (`None` = legacy behaviour) |
| Adapter `call` signatures gained `stale_timeout` + `on_heartbeat` kwargs | OpenAI, Anthropic, HermesXML — Local inherits from OpenAI |
| `JaegerAgent.stale_call_timeout_s = 30.0` (default) | Adapter fallback fires after 30s of no progress instead of waiting out the SDK timeout |
| `JaegerAgent.last_activity_ts` / `last_activity_desc` | "Last seen" diagnostic for TUI / gateway watchdog |
| `JaegerAgent.touch_activity(desc)` | Public helper so long-running tools can flag progress |
| `AgentCallbacks.heartbeat` | User-supplied liveness callback; fires ~10 Hz during model calls |
| [tests/.../test_liveness.py](../tests/jaeger_os/agent/test_liveness.py) | 12 tests |

### Behaviour
- A provider whose TCP socket is open but not sending bytes (the classic "API hang") now triggers `StaleCallTimeout` after 30 s. The agent's adapter-fallback chain catches it like any other adapter exception and tries the next backend.
- The TUI status bar can subscribe via `AgentCallbacks(heartbeat=...)` and surface "still waiting on the model (12.4 s)…" instead of looking frozen. The same callback is the gateway watchdog's keep-alive signal.
- Operator interrupts (`Ctrl-C`, voice barge-in) still win — `AgentInterrupted` propagates before the stale check fires on each poll tick.

## Priority 4 — Jittered backoff + prompt-cache upgrade

### What landed
| File | Purpose |
|---|---|
| [src/jaeger_os/agent/retry_utils.py](../src/jaeger_os/agent/retry_utils.py) | `jittered_backoff(attempt, base_delay, max_delay, jitter_ratio)` — exponential backoff with decorrelated jitter. `retry_with_backoff(fn, ...)` — convenience wrapper. Ports `python_hermes_agent.upstream.agent.retry_utils` |
| `AnthropicAdapter._mark_recent_message_cache(messages, n=3)` | New helper — marks system + last N messages with `cache_control` (Hermes "system_and_3" pattern). Replaces the previous "system + last user only" marker |
| `AnthropicAdapter._mark_last_user_cache` | Kept for the legacy single-marker use case |
| [tests/.../test_retry_utils.py](../tests/jaeger_os/agent/test_retry_utils.py) | 15 tests covering backoff curve, decorrelation, and Anthropic cache markers |

### Behaviour
- **Jittered backoff** decorrelates concurrent retries: multi-instance JROS deployments hitting the same rate-limited provider no longer all retry at the same instant. Pure helper — caller decides when to use it. Suitable for per-tool retry policy (transient 429/502/timeout) and adapter-level credential rotation.
- **Prompt caching upgrade**: previously marked only system + last user (2 cache breakpoints). Now marks system + last 3 messages (4 breakpoints — Anthropic's per-request limit). The win matters most for **multi-tool sequences** where every tool result is a fresh user turn — under the old scheme, only the most recent one hit cache; under the new scheme, all three recent turns + system match the cached prefix from the previous round.

## Aggregate test count

```
Before Phase 8:   905 passing (after Phase 7)
After Priority 1: 952 (+47 — coerce + sanitize tests)
After Priority 2: 960 (+8  — length-retry tests)
After Priority 3: 972 (+12 — liveness tests)
After Priority 4: 987 (+15 — retry_utils + cache tests)
```

Zero regressions in the pre-existing 905. Two pre-existing equality
assertions in adapter tests were broadened to allow the new
`finish_reason` field; both assertions still pin the original
behaviour, just with `==` replaced by per-field checks.

## What's deferred (high-impact but bigger lifts)

These came up in the Hermes review but weren't in this batch:

1. **Trajectory compression with LLM summary** — Hermes'
   `trajectory_compressor.py`. Protect first + last N turns,
   summarise the middle with an auxiliary model. ~2-3 days, high
   ROI on long sessions. Worth pairing with a slash command
   (`/compress`).
2. **Memory provider abstraction** — Hermes' `MemoryProvider` ABC
   with one-external-provider limit. ~6-8 hours. Unlocks future
   Honcho / OpenViking integration.
3. **Memory content scanning** — Hermes scans `memory` writes for
   injection / exfil patterns before writing. ~2-3 hours. Security
   win for the "model can write into the system prompt" surface.
4. **Skill source adapter pattern** — multi-source skill discovery
   (GitHub, marketplaces, local files). ~3-4 days. Future-proofing
   rather than immediate need.
5. **Trust levels (safe / caution / dangerous)** — upgrade JROS's
   binary `is_danger` verdict to Hermes' tri-state. ~1-2 days.
6. **Process registry watcher patterns** — Hermes' rolling output
   buffer + regex-based "notify when stdout matches" pattern. ~2-3
   days. Enables agent to tail long-running processes.

The Phase 8 priorities focused on **resilience** — making the existing
behaviour fail more gracefully. The deferred items are mostly about
**new capabilities** (long-session compression, external memory
backends, marketplace skills). Worth their own phase rather than
squeezing in.

## Public surface after Phase 8

```python
from jaeger_os.agent import (
    # Phase 1-7 (unchanged)
    JaegerAgent, AgentCallbacks, ToolDef, register_tool,
    Message, ToolCall,
    AnthropicAdapter, OpenAIAdapter, HermesXMLAdapter,
    LocalLlamaAdapter, MLXAdapter,
    JAEGER_TOOLSETS, resolve_toolsets,

    # Phase 8 additions
    coerce_args,                 # tool arg drift fixer
    schema_sanitizer,            # module — sanitize_tool_schemas etc.
    StaleCallTimeout,            # raised when a provider hangs
    jittered_backoff,            # backoff timing helper
    retry_with_backoff,          # convenience retry wrapper
)
```

`AgentCallbacks` gained `heartbeat` (liveness ticks) and
`JaegerAgent` gained `stale_call_timeout_s`, `last_activity_ts`,
`last_activity_desc`, and `touch_activity(desc)`.
