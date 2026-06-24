# Context-window guardrail

Pre-flight protection against the failure mode where Jaeger assembles
a prompt that's bigger than the model server's loaded context window
and the call hard-fails with `Requested tokens (X) exceed context
window of Y`.

## Two layers — reactive and preventive

| Layer | Where | Fires |
|---|---|---|
| **Reactive** | `jaeger_os.core.runtime.cloud_errors.friendly_error_text` | After the server returns 400. Rewrites the raw error into "Fix on the server side: …" advice. Already existed before this work. |
| **Preventive** | `jaeger_os.agent.util.context_guard` | Before any HTTP call. Estimates the assembled prompt's tokens; trims oldest history until it fits; raises `ContextOverflow` if even max trimming doesn't fit. |

The preventive layer is the new piece. It runs inside `JaegerAgent._one_model_step`
right before `adapter.format_messages`, so the adapter never sees an
oversized message list.

## What it does

```python
# At agent construction (build_jaeger_agent does this for you when
# ``ctx_window`` is passed — main.py pulls it from config.model.ctx):
guard = ContextGuard(ContextBudget(
    ctx_window=16384,          # match the server's loaded ctx
    reserve_for_completion=1024,
    safety_margin=256,
    chars_per_token=3.0,       # conservative — overshoots slightly
    max_tool_result_chars=24_000,
))
agent = JaegerAgent(adapter=..., context_guard=guard, ...)
```

Every turn the loop:

1. **Estimates** the prompt size via a char-based heuristic on the
   system prompt + every message in history + the tool-schema JSON.
2. **Trims** oldest non-system messages until the estimate fits the
   prompt budget (`ctx_window − reserve_for_completion − safety_margin`).
   The latest user message and any in-flight assistant/tool messages
   are *undroppable*.
3. **Raises** `ContextOverflow` if the undroppable set alone is too
   big. The exception carries the breakdown:
   `estimated`, `budget`, `system_prompt_tokens`, `tools_tokens`,
   `latest_user_tokens`.

A separate per-result truncator runs in `_dispatch_one_tool` *before*
the result is appended to messages: if a single tool returns more than
`max_tool_result_chars` chars of JSON, it's replaced with a preview +
size marker. Stops a 5 MB `run_shell` dump from poisoning the next turn.

## What the operator sees

Before this change, you saw the server's terse error post-failure:

```
✦ error
The model server loaded gemma-4-26B-A4B-it-Q4_K_M.gguf with a context
smaller than the prompt needs.
Fix on the server side: …
Raw error: Requested tokens (16628) exceed context window of 16384
```

After: the same kind of advice, but *before* anything is sent — and
with exact token-budget numbers from the estimator:

```
Refused to send: this turn's prompt won't fit Jaeger's context budget
(15104 tokens of usable prompt room).

  prompt estimate:   ~16628 tokens
  system prompt:     ~3200 tokens
  tool schemas:      ~8400 tokens
  latest user msg:   ~120 tokens

Fix one of:
  • Raise config.model.ctx (and reload the model on the server so its
    loaded ctx matches — LMStudio 'Context Length', Ollama 'num_ctx').
  • Send a shorter message, or break the request into steps.
  • Narrow the active toolsets — the tool-schema JSON itself is a few
    thousand tokens with all toolsets active.
```

## Estimator: why a char heuristic?

Real tokenizers (tiktoken, HF tokenizers) need 5–50 MB of vocab files
and differ per model family (gemma ≠ qwen ≠ llama ≠ GPT-4). A
char-based heuristic with a **conservative ratio** (3.0 chars/token by
default, real ratio is ~3.5–4.0 for English) gets us to within
~15-25% accuracy with zero deps and zero per-turn cost.

The bias is deliberate: we'd rather trim one extra turn than miss the
budget by one token. The 256-token safety margin in
`ContextBudget` is the same bias in numeric form.

If you need exact counts later, swap the implementation of
`ContextGuard.estimate_text_tokens` to call into a real tokenizer
(the surface is one method) — nothing else has to change.

## Trimming policy

**Preserved on every trim:**
- The system prompt.
- The most recent user message.
- Every assistant/tool message that comes after that user message
  (the in-flight turn — dropping the assistant's tool call but
  keeping the user's question would confuse the model).

**Dropped, oldest-first, until the estimate fits:**
- Older user messages, assistant replies, and tool returns.

**Refused** (raise `ContextOverflow`):
- System prompt + tool schemas + latest user message + in-flight chain
  alone still over budget. Nothing safe to drop. Caller must shorten
  the user's input or raise `config.model.ctx`.

When trimming happens, the agent fires `on_thinking("[context-guard]
trimmed N old message(s) to fit ctx budget")` so the TUI/log shows
what happened.

## Per-tool-result truncation

A second small guard runs in `_dispatch_one_tool` after the tool
returns but before its result is appended to `messages`:

```python
content, was_truncated = guard.truncate_oversized_result(content)
if was_truncated:
    # Original was logged out-of-band; in-context replacement is a
    # short preview + a size marker so the model knows what it lost.
```

The check uses `max_tool_result_chars` (default 24 000 chars ≈ 8 K
tokens) and keeps the first `preview_chars` (default 1 500) of the
serialised result. For dict-shaped results (the common case in JROS),
the replacement is a marker dict so callers that index into the result
don't crash on a string.

Setting `max_tool_result_chars=0` disables this layer entirely —
useful for benchmarks that need full-fidelity tool outputs.

## Not yet (deferred)

- **Query the server for its actual ctx.** Today we trust the
  configured value. LMStudio's `/v1/models` and Ollama's `/api/show`
  both expose the loaded ctx; reconciling against the config would
  catch "you set ctx=16384 but loaded the model at 8192" mismatches
  before the first turn.
- **Real tokenizer.** Char heuristic is good enough for the
  guardrail-overshoots-slightly use case. If we need precise budget
  enforcement later, swap `estimate_text_tokens` to call
  `tokenizers.Tokenizer.encode(text).ids` for the loaded model's
  tokenizer.
- **History summarisation.** When trimming kicks in, we drop old
  messages outright. A future version could replace the dropped
  messages with a short LLM-generated summary — keeps the model
  contextualised at the cost of one extra turn.

## Disabling the guard

Pass `ctx_window=None` (or omit it) to `build_jaeger_agent` and no
guard is installed — the loop behaves exactly as before this change.
That's the default for bench paths that need to measure raw model
behaviour without overshoot bias.
