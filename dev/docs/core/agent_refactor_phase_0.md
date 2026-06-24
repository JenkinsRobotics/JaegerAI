# Phase 0 — JROS Agent Layer Refactor Audit

Pre-flight document for the pydantic-ai → JaegerAgent refactor. Maps every
load-bearing piece of the current implementation onto a target home in the
new framework, calls out the friction points to resolve before Phase 1, and
fixes the benchmark contract so we can measure pre/post objectively.

**Status:** investigation done · code changes deferred to Phase 1.

---

## 1. Executive summary

| Slice | Current LOC | Migration shape |
|---|---|---|
| pydantic-ai imports in `src/` | **11 files** | All replaced or deleted |
| pydantic-ai imports in `tests/` | **7 files** | All ported to new types |
| Custom Model wrappers (`LlamaCppModel`, `MlxModel`) | ~1000 lines | **Reused** — most logic is drift parsing / arg repair / dedup, framework-agnostic |
| `_run_via_iter` + helpers (the loop body) | ~250 lines | **Rewritten** as `JaegerAgent.run_turn` with explicit hook points |
| External model client | ~250 lines | Replaced by `AnthropicAdapter` + `OpenAIAdapter` |
| Skill registration via `@agent.tool_plain` | ~50 sites in `main.py` | Switch to `@register_tool` decorator + thin adapter for `skill_loader.py` |
| Benchmark suite | **1 function port** | Entry point is framework-agnostic ✓ but `_runner.py:_walk_messages_for_calls` walks pydantic-ai message types — needs replacing with a walk over the new `Message` list. ~20 LOC. |
| Test rewrites | ~7 files | Replace `pydantic_ai.messages.*` with the new internal `Message` TypedDict |

**Total rough effort:** 2–4 weeks of focused work. The drift parser, guardrail,
budget, history compaction, and system-prompt re-seating logic — all the
recent investment — **transfer cleanly**. The work is in writing the loop and
adapter shells around them, and in updating the tests that bind to
pydantic-ai's type names.

---

## 2. pydantic-ai surface — exact inventory

### Source (`src/jaeger_os/`)

| File | What it imports | Migration |
|---|---|---|
| `main.py:38-48` | `Agent`, `CallToolsNode`, `ModelRequestNode`, every `messages.*` part, `RequestUsage` | Replace with internal `Message` TypedDict + `JaegerAgent` |
| `main.py:1710` (inside `build_agent`) | `pydantic_ai.Tool` for MCP wrapping | New `ToolDef` covers this; MCP tools converted at registration time |
| `core/llm_model.py:693-701` | `Model`, `ModelMessage`, `ModelRequestParameters`, `ModelResponse`, `TextPart`, `ToolCallPart`, `ToolReturnPart`, `UserPromptPart`, `ModelSettings`, `RequestUsage` | `LlamaCppModel` ABCs go away; the function becomes "given OpenAI-style messages + tools, call llama-cpp, return OpenAI-style completion." All drift / repair / normalize / dedup helpers stay verbatim |
| `core/mlx_model.py:23-25` | Same as `llm_model.py` | Same shape — subclass chain dissolves into two flat call functions sharing the helpers |
| `core/external_model.py:117-139` | `OpenAIChatModel`, `OpenAIProvider`, `AnthropicModel`, `AnthropicProvider` | Replaced by direct `openai` / `anthropic` SDK calls inside `OpenAIAdapter` / `AnthropicAdapter` |
| `core/tool_result_budget.py:32` | `ToolCallPart`, `ToolReturnPart` (for `compact_history`) | Operates on `Message` dicts instead — simpler |
| `core/memory.py`, `core/instance.py`, `core/prompts.py`, `core/tools/__init__.py`, `core/tools/memory.py`, `core/tools/vision.py` | Indirect references (type hints / re-exports) | Either drop the hint or update to the new internal type |

### Tests (`tests/jaeger_os/`)

| File | Bound to | Migration |
|---|---|---|
| `core/test_tool_call_repair.py` | `ToolCallPart` | Build `Message` dicts directly with `tool_calls: [...]`; the underlying logic is unchanged |
| `core/test_tool_result_budget.py` | `ToolCallPart`, `ToolReturnPart` | Same — `compact_history` becomes dict-walking, tests use dict fixtures |
| `core/test_session_resume.py` | `ModelRequest`, `SystemPromptPart`, `UserPromptPart` | `_ensure_system_prompt` operates on the new `Message` list; rewrite fixtures |
| `core/test_native_handler.py` | `ModelMessage` subclasses | The native-vs-Hermes-XML toggle moves to the adapter level; tests follow |
| `core/test_session_state.py` | `ModelRequest`, `UserPromptPart` | Rewrite fixtures |
| `core/test_tier_gating.py` | `pydantic_ai.Agent` (lazy import) | Switch to `JaegerAgent`; tier-gating logic is independent of the framework |
| `core/test_mlx_backend.py` | `pydantic_ai.messages`, `pydantic_ai.models.ModelRequestParameters` | Just-shipped; trivially rewritten for the new bridge |

**No test imports `CallToolsNode` / `ModelRequestNode`** — pydantic-ai's graph
nodes are only referenced inside `main.py`'s loop body. That's the
cleanest possible split: the framework escape is contained.

---

## 3. Feature port map — what `_run_via_iter` does, where it goes

Every load-bearing pattern in the current loop, with its target home in
`JaegerAgent`. **Anything in this table is a Phase 1 deliverable, not a
"discover during migration" gap.**

| Feature | Current location | Target in JaegerAgent |
|---|---|---|
| Cancel event (Ctrl-C / voice barge-in) | `main.py:1980-1996` `begin_turn_cancel_scope` | `JaegerAgent._interrupt_event` + `interrupt()` method per spec §4.3 |
| Per-turn loop budget (`_MAX_TOOL_CALLS = 24`) | `main.py:1909-1915` | `max_iterations` constructor arg per spec §5.6 |
| Identical-call counter (`_MAX_IDENTICAL_CALLS = 4`) | `main.py:1946-1971` `_loop_halt_reason` | `JaegerAgent._call_signature_counts` + halt check between turns |
| Semantic-failure counter (`_MAX_SEMANTIC_FAILURES = 2`) | `main.py:1914-1944` `_semantic_failure_signature` | Same — counted inside the agent loop, function moves verbatim |
| `ToolGuardrail` (warn one step before halt) | `core/tool_guardrails.py` | `before_call` / `after_call` callbacks on `JaegerAgent`; existing module stays |
| `TurnResultBudget` (persist oversized payloads) | `core/tool_result_budget.py` | `after_call` callback — runs on the parsed tool return before it's appended to messages |
| `compact_history` (prune old payloads) | `core/tool_result_budget.py:compact_history` | `between_turns` callback OR pre-format hook; operates on the new `Message` list |
| `_ensure_system_prompt` (re-seat after resume) | `main.py:645-675` | Runs inside `JaegerAgent.run_turn` before format-messages |
| Skip-final pattern (`SKIP_FINAL_TOOLS`) | `main.py:89-150` + `_fast_finalize_sync` (1778) | New `JaegerAgent` constructor arg `skip_final_tools: set[str]`; loop checks before dispatching the LAST tool call |
| Fix-loop retry (`run_python` failures) | `main.py:2453-2510` `_run_with_fix_loop` | A retry policy attached to specific tools — or, more cleanly, a separate "retry wrapper" tool dispatcher. **Decide in Phase 1.** |
| Inline think (`JAEGER_INLINE_THINK`) | `main.py:2295-2380` | `pre_turn` hook on `JaegerAgent` — augments the user message before it's appended |
| `_session_state` carry-forward | `main.py:816-840` `_update_session_state_from_iter` | Hook on `after_turn`; same logic, walks new messages instead of pydantic-ai nodes |
| `_sanitize_history_messages` | `main.py:841-861` | Trivial — operates on the appended `Message`s instead of pydantic-ai parts |
| `_pair_tool_messages` / `_walk_new_messages` (TUI display) | `main.py:769-815` | Becomes a pure walk over the new `Message` list — actually *simpler* |
| Drift parser (`<tool_call>…</tool_call>` salvage) | `core/llm_model.py:_extract_drift_tool_calls` | **Stays verbatim.** Lives inside `HermesXMLAdapter.parse_response` and the local-model adapters that need it |
| `_parse_drift_payload` (Gemma quote-token recovery) | `core/llm_model.py` | Same — stays verbatim |
| `_repair_tool_call_arguments` + `_normalize_tool_name` + dedup | `core/llm_model.py` | Same — stays verbatim, called from the adapter's parse step |
| `file_read` unchanged-read dedup | `core/tools/files.py` | Tool-level; no framework dependency. Untouched. |
| MCP tool registration | `main.py:1710` `Tool(...)` wrapping | New `register_tool` decorator + a thin runtime registration path for MCP-discovered tools |

### What's NOT in the spec but must be ported

These are JROS-specific patterns the spec hasn't called out by name. **Add
them to Phase 5 explicitly:**

- **Skip-final tool intercept** — when a single deterministic tool answers the turn (`get_time`, `calculate`, `recall`, etc.), `_run_via_iter` short-circuits the agent loop and uses `_fast_finalize_sync` to phrase the result. This is a measurable latency win and one of JROS's defining behaviors.
- **Cancel event mid-tool** — long-running tools (`run_python`, `terminal`) poll `tool_interrupt.is_interrupted()` to halt mid-execution. The cancel event must be threaded through the new loop AND remain accessible to tools.
- **Per-turn `large_results/` cleanup** — `TurnResultBudget` writes oversized tool returns to disk and prunes the dir. The hook point for "turn started" needs to fire `reset_read_tracker()` (file_read dedup) and any other per-turn resets.
- **`_ensure_system_prompt` after every turn**, not just at boot — handles the overflow-trim edge case.

---

## 4. ExternalModelClient → adapter map

`core/external_model.py` is a thin wrapper that picks between pydantic-ai's
`OpenAIChatModel` / `AnthropicModel` based on `config.external_model.provider`,
then does a connectivity check. The new framework replaces it with:

| Provider slug | New adapter | Notes |
|---|---|---|
| `openai`, `openai-codex` | `OpenAIAdapter(base_url="https://api.openai.com/v1", ...)` | Direct `openai.OpenAI` client |
| `anthropic` | `AnthropicAdapter(api_key=..., model=...)` | Direct `anthropic.Anthropic` client; prompt caching applied |
| `gemini` | `OpenAIAdapter(base_url=Google's compat endpoint, ...)` | Gemini's OpenAI-compatible surface — no separate adapter needed |
| `ollama-cloud`, `ollama`, `lmstudio` | `OpenAIAdapter(base_url="<server>/v1", api_key="not-required")` | Same OpenAI-compatible HTTP path |
| `local` (llama-cpp-python in-process) | A direct call function (no HTTP adapter) | Bypass HTTP — keep the in-process path |
| `mlx` (mlx-lm in-process) | A direct call function | Same — in-process bypass |

**Connectivity check** (the thing that currently silently falls back to
local on a 400) becomes a `health_check()` method on each adapter, called
explicitly by `make_client` — so the fallback decision and its
user-facing message stay where they belong (the slash command), not
buried in adapter internals.

---

## 5. Skill loading + dynamic tool registration

This is the spec gap that bothered me most. The current model:

- `core/skill_loader.py` walks `<instance>/skills/` and `src/jaeger_os/skills/`, imports each skill package, calls its `register(agent)` function, and the skill registers tools via `@agent.tool_plain`.
- Smoke tests gate registration — a skill that fails its smoke test does not get its tools wired up.
- Versioned packages (`get_time_v2`) override built-ins of the same name.
- All of this happens **after** `JaegerAgent` is constructed (or its equivalent).

The spec's `@register_tool` decorator is module-level at import time. Two
ways to bridge:

**A. Late registration on the agent instance.** Mirror pydantic-ai's
current behavior — `JaegerAgent` exposes `agent.register_tool(...)` that
the skill loader calls per skill. The module-level decorator is a thin
wrapper that records into a global registry, plus the loader injects
skill tools at boot.

**B. All-static registration.** Move every skill to the module-level
decorator pattern. Loses smoke-test gating and dynamic enable/disable.

**Recommendation: A.** The decorator is the *common* path (built-in
tools), `agent.register_tool` is the *dynamic* path (skills + MCP). The
spec's Section 4.1 needs one extra method signature; the loader's
behavior survives unchanged.

---

## 6. Benchmark plan — pre / post comparison

**The good news:** `benchmark/levels/_runner.py:57-112` uses
`boot_for_tui` as the entry — framework-agnostic. The contract that has
to stay stable across the refactor:

1. `boot_for_tui(instance_name=...)` keeps returning an object with
   `.client`, `.layout`, `.cleanup()`.
2. `run_command(client, user_text, session_key=...)` keeps writing log
   rows and updating session state.
3. The log row schema (`{user, session_key, answer, tool_calls,
   tool_activity, decision, skipped_final, latency}`) stays stable.

Those three are the **agent-loop public contract** for benchmarks.

**The one port the benchmark needs:** `_runner.py:70-103`
`_walk_messages_for_calls` walks pydantic-ai's `result.all_messages()`
to extract the per-turn tool sequence — it reads `msg.kind`,
`part.part_kind == "tool-call"`, etc. Post-refactor, the same function
walks the new `Message` dict list. Two clean approaches:

- **(A)** Have `run_command` write the tool sequence directly into the
  latency log row at turn end. Benchmark reads it from there. Decouples
  the benchmark from message internals entirely.
- **(B)** Update `_walk_messages_for_calls` to walk the new `Message`
  dicts. ~20 LOC change inside the benchmark runner.

Recommendation: (A). It's the more durable answer — the next time
internal message shapes change, the benchmark won't have to follow.

### Baseline capture (do BEFORE Phase 1)

Run all four levels against the current pydantic-ai-based code and
freeze the JSONL row files + scores. These become the comparator:

```bash
cd /Users/jonathanjenkins/GITHUB/JROS
python -m benchmark.levels.level1_routing   > benchmark/baseline/level1.log 2>&1
python -m benchmark.levels.level2_multistep > benchmark/baseline/level2.log 2>&1
python -m benchmark.levels.level3_multiturn > benchmark/baseline/level3.log 2>&1
python -m benchmark.levels.level4_recovery  > benchmark/baseline/level4.log 2>&1
```

Plus copy `level_{1,2,3,4}_rows.jsonl` into `benchmark/baseline/` so the
exact tool-sequence observations are frozen.

### Post-Phase-1 comparison

Same four commands against the JaegerAgent build. The diff between the
two `_rows.jsonl` sets is the answer to "did the new framework regress
anything?" — same prompts, same scoring, fair comparison.

### Metrics worth tracking

Current rows include `latency` per turn. Useful, but not the whole
picture. Add to the row schema (Phase 1 work — small):

- `time_to_first_token` — for streaming-capable adapters
- `time_to_first_tool_call` — when the first tool fires
- `tool_dispatch_count` — count of tools dispatched
- `iteration_count` — agent-loop iterations to completion
- `framework` — `"pydantic-ai"` or `"jaeger-agent"` (so historical rows are unambiguous)

### Targets (not commitments — just what success looks like)

| Level | Current | After refactor goal |
|---|---|---|
| L1 routing (one-shot) | 97% | ≥97% — no regression |
| L2 multi-step | 83% | ≥83%; likely better because the loop is less rigid |
| L3 multi-turn | 67% | ≥75% — the resume + history-compaction work pays off here |
| L4 recovery | (current %) | ≥same |
| Median latency, fast tier | (capture baseline) | ≤ baseline, ideally faster |

---

## 7. Open questions — answered or deferred

The spec flagged seven; here's my read on each. Push back where you disagree.

| # | Question | My read | Rationale |
|---|---|---|---|
| 1 | Package layout: `jaeger_base` vs in-place inside `jaeger_os` | **In-place.** Add `src/jaeger_os/agent/` and migrate. `JaegerNode` / `JaegerPlugin` / ZMQ from the spec don't exist in JROS today — they look like notes from a future humanoid-platform fork. Don't pre-build them. | Avoids churning unrelated structure |
| 2 | Streaming as default? | **Off for v1, callbacks for live updates.** Streaming wins help TTS-first / voice paths; the TUI is already callback-driven. | Match the spec; revisit when voice latency is in scope |
| 3 | Session storage backend | **Reuse existing.** Jaeger has `episodic.jsonl` + `external_model_history.json` + `facts.json`. No new SQLite. | Don't double up on state stores |
| 4 | Subagent semantics (`jros_delegate`) | **Defer to Phase 5+.** Not in critical path. | Spec already flags this |
| 5 | Pydantic v1 vs v2 | **v2.** Already what JROS uses (`model_dump`, `model_json_schema`). | Confirmed against current code |
| 6 | Logging — should callbacks feed `JaegerLogger`? | **Yes,** via a default callback that adapts `tool_progress` / `step` / `error` into existing log rows. Keeps the existing dashboards working. | Continuity |
| 7 | Fix-loop retry — does it live in the framework or per-tool? | **Per-tool retry policy** attached at registration time: `@register_tool(..., retry_on=(SyntaxError, ExecError), retry_prompt_template=...)`. The framework owns the mechanism; tools opt in. | Cleaner than a special outer loop for `run_python` |

**One I'd add to your spec:** how does `MCPSpec` / MCP server tools get
into the registry? Spec section 4.1 assumes all tools are decorated; MCP
tools are runtime-discovered. Answer: same path as skills — late
`agent.register_tool(...)` from the MCP bridge at boot.

---

## 8. Phase 1 entry criteria

Before any code goes into `src/jaeger_os/agent/`, these need to be true:

- [x] Phase 0 audit reviewed (this document)
- [ ] Open questions answered or accepted (section 7 above)
- [ ] Baseline benchmark numbers captured into `benchmark/baseline/`
- [ ] Decision on tool-registry shape: module-decorator + `agent.register_tool` (recommended)
- [ ] Decision on per-tool retry vs outer retry loop (recommended: per-tool)
- [ ] The reference Hermes-agent's recent local-model runtime additions reviewed (the user mentioned recent commits worth lifting)

When all six are checked, Phase 1 (`Core skeleton + AnthropicAdapter`)
can start cleanly.

---

## 9. What does NOT change

For continuity — these are part of JROS's public surface and the refactor
must preserve them exactly:

- **`boot_for_tui(instance_name=...)` signature and return shape** — the
  benchmark suite, the TUI, the daemon entry all depend on it.
- **`run_command(client, user_text, session_key=...)` signature.**
- **Per-turn log row schema** in `<instance>/logs/latency.jsonl`.
- **The `<instance>/` directory layout** (`identity.yaml`, `config.yaml`,
  `memory/`, `skills/`, `logs/`, `credentials/`).
- **Slash command catalog** (`/model`, `/runtime`, `/skills`, …) — handler
  internals may move, the names stay.
- **Skill `SKILL.md` frontmatter contract** — names, descriptions, tags,
  platforms, requires_tools, etc.
- **All built-in tool names + signatures.** The agent learns them; we
  don't break them.

Anything not on this list is fair game to refactor.

---

*Next: capture the baseline benchmark numbers, then begin Phase 1.*
