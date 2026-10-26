# Lean tool surface — pull, not push

The agent's per-turn overhead used to be ~25K tokens before any
conversation history: ~2.6K tokens of system prompt + ~22.7K tokens of
tool-schema JSON for all ~77 registered tools. On a 16K-ctx local
model, that's 68% of the budget burned on framework before any
*task* gets a token.

The lean tool surface changes the shape: the model sees **20 CORE
tools every turn + a 1-line catalog of every other category**. When
it needs a specific hidden tool, it calls `describe_tool("name")`
to fetch the schema; when it needs a whole category, it calls
`load_toolset("category")` to widen its active set for the rest of
the session.

## Numbers

| Mode | Tools visible | Tool schemas (chars) | Tool schemas (tokens) |
|---|---|---|---|
| Lean OFF *(default)* | All ~77 | ~79,700 | ~22,700 |
| **Lean ON** *(opt-in: `JAEGER_TOOLSET_SCOPING=1`)* | 20 CORE + skill toolsets + categories the model loads on demand | ~5,000 | ~1,400 |

> **Status (0.1.0):** opt-in only. We briefly defaulted ON after adding
> `describe_tool` + the catalog, but a/b benching against v5 showed
> Gemma 4 26B-A4B routing dropped 6 points under the lean default and
> Gemma-4-E2B dropped 18 points. Reverted to OFF until
> *auto-load-on-intent* (a future track that picks toolsets without
> requiring a meta-step from the model) lands and a re-bench shows
> no regression.

That's a **~94% reduction in tool-schema overhead**. On a 16K-ctx
model the prompt-prefix budget drops from ~25K tokens (overflowing) to
~3.5K — leaves ~12.5K for the actual task instead of ~5K (or
overflow).

## How the model uses it

The system prompt teaches the pattern with a runtime-tail note:

```
- You see a focused CORE set of tools. The categories below list every
  OTHER tool that's installed but not currently in your active set.
  Two ways to reach them:
    • describe_tool("name") — peek at one tool's exact schema
      without loading anything. Cheap.
    • load_toolset("category") — add a whole category to your
      active set for the rest of the session.

TOOL CATALOG — categories you can describe_tool / load_toolset:
  • files          — append, delete, patch, search files; list the workspace
  • code           — run Python, shell/terminal, install packages, venv exec
  • media          — text-to-speech, mic capture, vision, image generation
  • scheduling     — schedule, list, cancel cron prompts
  • background     — long-running background processes; open URLs/apps
  • skills         — reload, package, benchmark skills; deep-think queue
  • board          — the kanban task board
  • credentials    — list and read stored credentials
  • plugins        — list, set up plugins; send messages
  • models         — list and download models
  • delegation     — hand subtasks to sub-agents
```

So when the model wants `run_python`, it has three choices, in order
of cost:

1. **One-shot peek** — `describe_tool("run_python")`. Returns the
   schema only. One extra turn before the actual call. Best for *"I
   only need this tool once."*
2. **Load the category** — `load_toolset("code")`. Adds all five
   `code` tools to the active set; the model sees their full schemas
   on every subsequent turn. Best for *"I'm doing several code things
   in a row."*
3. **Direct call** — try `run_python(...)` straight away. The agent's
   FULL registry validates the call, so a well-formed one succeeds
   even though the schema wasn't in the prompt. The drift parser /
   adapter handles this transparently in the Hermes-XML path. The
   first time it works because Gemma 4 / Qwen / Llama have seen many
   tool calls during training and can guess.

## How the agent uses it

`JaegerAgent` now distinguishes two collections:

  - `agent.all_tools` — every registered ToolDef. Used for dispatch +
    validation + the `describe_tool` lookup. Never shrinks.
  - `agent.tools` — a `@property` that filters `all_tools` through
    `tool_visible(name)` on every access. Recomputes per-turn, so a
    `load_toolset` call mid-session widens the view on the very next
    `_one_model_step` without an agent rebuild.

```python
# src/jaeger_os/agent/loop/jaeger_agent.py
@property
def tools(self) -> list[ToolDef]:
    if self._tools_filter_locked:
        # Explicit ``tools=[...]`` at construction — caller knows best.
        return list(self._all_tools)
    from jaeger_os.core.skills.toolsets import tool_visible
    return [t for t in self._all_tools if tool_visible(t.name)]
```

`adapter.format_messages(self.messages, self.tools, ...)` then naturally
ships only the visible schemas. No adapter changes needed — they
already iterate the list they're handed.

## Visibility rules — `tool_visible(name)`

A tool is visible iff:

1. **`JAEGER_FULL_TOOLS=1`** — all tools visible (bench mode).
2. **In `CORE`** — the 20-tool always-on set (introspection + memory
   + minimal IO + the meta-tools).
3. **In an active toolset** — `load_toolset(name)` added it.
4. **In NO declared toolset** — fail-open. A new tool that nobody
   classified yet stays visible by default, never silently hidden.

## Configuration

| Env var | Default | Effect |
|---|---|---|
| `JAEGER_TOOLSET_SCOPING` | unset (off) | Set to `1` to opt INTO the lean surface. |
| `JAEGER_FULL_TOOLS` | unset | Kill-switch — if `1`, forces the full surface even when scoping is asked for. Honoured for backwards compat with the bench harness. |

The 0.1.0 bench (`benchmark/levels/history/BENCHMARK_v0.1.0_baseline.md`)
re-validated that lean OFF is the right default: with the corrected
umbrella-aware scorer, gemma-4-26B-A4B routes at 97.1% with lean off
vs 73.5% with lean on. The `describe_tool` + catalog pattern helped
the smallest Gemma 4 model (E4B) by +3 points but hurt the rest by
−6 to −18. Until *auto-load-on-intent* eliminates the meta-step,
lean stays opt-in.

## CORE membership

20 tools, deliberately small. Picked for high-frequency use across
both chat and agent workloads:

```
get_time         calculate         system_status
remember         recall            forget
list_facts       search_memory
set_name         update_soul
web_search       web_extract       get_weather
read_file        write_file
help_me          clarify
todo
load_toolset     describe_tool          ← meta-tools, always reachable
```

If the model needs anything else — files-beyond-read-and-write, code
execution, scheduling, media, computer use, skills management, the
kanban board — it has to either peek or load.

## Trade-offs

**KV-cache hits.** The CORE schema is small and stable per session, so
the cache prefix stays cached across turns. When `load_toolset` fires,
the prefix grows once and the cache backfills the next turn — *worse*
than a fully-cached fixed prefix but *better* than today's all-tools-
every-turn prefix, which is huge AND varies per session as skills get
registered.

**Latency for "new" tools.** A tool the model hasn't seen this session
costs one extra turn (the `describe_tool` round-trip). On a 50ms-token
local model, that's ~2-5 seconds per first-use of a hidden tool —
real but rare.

**Model behaviour.** Some smaller models may try to call hidden tools
directly without describe_tool. The agent's registry still validates
+ dispatches correctly when the call is well-formed, so this is a
slight performance loss (an extra round-trip when the model guesses
wrong about parameter names) not a correctness loss.

## What's still ahead

- **System-prompt minification** (lever C from the original options).
  At ~2,200 tokens the system prompt is no longer the dominant cost,
  but trimming OPERATING_DISCIPLINE / MANDATORY_TOOL_RULES into
  lazy-fetchable docs could shave another 1.5K tokens.
- **Cloud-adapter slim mode.** OpenAI / Anthropic native tool-calling
  requires schemas upfront. Their context windows (128K-200K) make
  the overhead moot, but if you want symmetric behaviour we'd need
  to map the lean surface through the native protocol — currently
  cloud adapters still get whatever `agent.tools` returns, which is
  already the lean set.
- **Auto-load on intent.** A future trick: a pre-routing pass guesses
  which toolset the user's prompt needs, calls `load_toolset` before
  the main turn fires. Avoids the explicit meta-step. Worth A/B-ing
  once the catalog-pattern bench numbers are in.
