# Phase 6 — Partial Migration

**Status:** Phase 6.1 (parallel-path migration with feature flag) landed.
Full removal of `pydantic-ai` deferred to Phase 6.2 pending A/B benchmark
signal.

## What Phase 6.1 ships

A **parallel implementation** of the JROS agent loop driven by
`jaeger_os.agent.JaegerAgent` (the framework-free loop built in Phases
1-5), running alongside the existing pydantic-ai loop and selected at
runtime via `JAEGER_USE_NEW_AGENT=1`.

Why parallel instead of cutover: 48+ tool registrations live in
`main.py`, plus skill-loader registrations, plus benchmark suite
binding to pydantic-ai message types. A flag flip is reversible if
the A/B signals regression; a cutover isn't.

### Files added

| File | Purpose |
|---|---|
| [src/jaeger_os/agent/bridge.py](../src/jaeger_os/agent/bridge.py) | `mirror_pydantic_ai_tools(pai_agent)` — walks the live pydantic-ai agent's tool registry and registers each tool into the new framework-free registry. Synthesises a Pydantic args model from each function signature. |
| [src/jaeger_os/agent/runtime_bridge.py](../src/jaeger_os/agent/runtime_bridge.py) | `build_jaeger_agent(client, ...)` selects the right adapter from a JROS client (LocalLlama / Anthropic / OpenAI). `drive_one_turn` runs one turn and returns a legacy-compatible dict. `jaeger_agent_enabled()` reads the env-var gate. |
| [benchmark/run_ab.py](../benchmark/run_ab.py) | A/B benchmark driver — boots once, runs all 4 levels with legacy, then all 4 with `JAEGER_USE_NEW_AGENT=1`. |
| [benchmark/ab_report.py](../benchmark/ab_report.py) | Reads both row sets, emits a markdown scorecard + flipped-prompt diff + latency deltas. |

### Files modified

| File | Change |
|---|---|
| [src/jaeger_os/main.py](../src/jaeger_os/main.py) | `_get_agent` mirrors tools when gate is on. `_run_turn` dispatches to `_run_turn_via_jaeger_agent` when gate is on. ~110 lines added; no legacy code removed. |
| [benchmark/levels/_runner.py](../benchmark/levels/_runner.py) | `run_turn` dispatches to `_run_turn_via_new_agent` when gate is on. Same `TurnRow` shape returned either way. |

### What the bridge guarantees

- **Same tool surface** — every tool the pydantic-ai agent knew about
  is mirrored into the new registry with the same name, description,
  argument validation, and underlying function.
- **Same skip-final list** — `SKIP_FINAL_TOOLS` from `main.py` feeds
  `JaegerAgent.skip_final_tools` directly.
- **Same fast-finalize phrasing** — the new agent's
  `skip_final_finalizer` calls the legacy `_fast_finalize_sync` so
  conversational tone is identical.
- **Same backstop ceiling** — `max_iterations=24` matches the legacy
  `_MAX_TOOL_CALLS`.
- **Same row schema** — the latency log row and the bench `TurnRow`
  carry the same keys; only `framework_path` distinguishes the two
  runs.

## Open work — Phase 6.2 (full cutover)

Once the A/B confirms parity or improvement on Levels 1-4:

1. **Remove `@agent.tool_plain` decorators in `main.py`** — switch all
   48 sites to `@register_tool(name=..., description=..., args_model=...)`
   directly. The synthetic-args-model bridge step goes away.
2. **Skill loader migration** — `skill_loader.load_and_register(agent, ...)`
   takes a pydantic-ai agent today. Add a sister entry point that
   takes the new tool registry and have skills opt in.
3. **`_run_via_iter` deletion** — once `_run_turn_via_jaeger_agent` is
   the only path, the pydantic-ai loop driver goes away (~250 lines).
4. **`_walk_new_messages` deletion** — only used by the legacy path.
5. **`build_agent`/`Agent` deletion** — `pydantic_ai.Agent` is no
   longer constructed.
6. **`pydantic-ai` from `pyproject.toml`** — the import is gone.
7. **Test fixture migration** — the 7 test files binding to
   `pydantic_ai.messages.*` get rewritten against the internal
   `Message` TypedDict (Phase 0 audit §2).
8. **Benchmark `_walk_messages_for_calls` deletion** — only the new
   path walker (now in `_run_turn_via_new_agent`) survives.

Estimated effort for Phase 6.2: 1-2 days once the A/B says "go."

## How to A/B

```bash
cd /Users/jonathanjenkins/GITHUB/JROS
.venv/bin/python benchmark/run_ab.py
.venv/bin/python benchmark/ab_report.py -o benchmark/AB_REPORT.md
```

The first command boots the model once, runs all 4 levels twice (~25
min on M4). The second reads the two row sets and emits a per-level
scorecard.

### Rollback

Unset the env var. The legacy pydantic-ai path resumes immediately;
no state is persisted that the legacy path can't read.

## Sanity gates passed before Phase 6.1

- ✅ Bridge tests green (9 tests cover mirror correctness, idempotency,
  schema rendering, args-model synthesis).
- ✅ Runtime bridge tests green (24 tests cover adapter selection
  across all client shapes, drive_one_turn output schema, halt
  reasons, multi-turn accumulation, env-var gate truthiness).
- ✅ Full repo suite: 881 passed (up from 848 = +33 new tests, 0
  regressions in pre-existing tests).
- ✅ End-to-end smoke: `JAEGER_USE_NEW_AGENT=1` + `what time is it?`
  returns a correct answer via `LocalLlamaAdapter` →
  `get_time` skip-final dispatch → `_fast_finalize_sync` phrasing.
  `framework_path=jaeger_os_agent`, `iterations=1`,
  `skipped_final=True`.

## What this does NOT change

Per the Phase 0 audit's "what NOT to change" list, all preserved:

- `boot_for_tui` signature + return shape
- `run_command` / `run_for_voice` signatures
- Per-turn latency log row schema (additive new keys: `framework_path`,
  `iterations`, `halt_reason`)
- `<instance>/` directory layout
- Slash command catalog
- SKILL.md frontmatter contract
- Every built-in tool name + signature
