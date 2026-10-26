# Main loop — architecture review & rebuild plan

A no-rock-unturned review of how JROS's pipeline works — tools, skills,
plugins, TUI and the agent loop — and a plan to rebuild it. Source: a
full read of `main.py` (~3,880 lines) + the connective modules.

## How a turn flows today

```
input (TUI typed / voice / cron / messaging / daemon)
  → run_command()      [prints to stdout, returns None]      ─┐ ~95%
  → run_for_voice()    [returns a dict]                       ─┘ duplicated
      → _run_with_fix_loop()   inline-think pre-pass + retry passes
          → _run_via_iter()    the agent.iter() drive loop
              · skip-final intercept (SKIP_FINAL_TOOLS)
              · loop backstop (_loop_halt_reason)
              · cancel-event check
              → pydantic-ai Agent  →  LlamaCppModel.request()  →  llama-cpp
```

Everything coordinates through one module-global dict, `_pipeline`
(`main.py:339`), and one `llm_lock`. Tools register onto the `Agent`
once (cached); code skills register *more* tools; playbook skills are
reached through the `skill` tool; plugins sit behind tools or are
re-exported (MCP). Deep Think swaps the model and re-runs the skill
loader to build new skills.

## The 5 areas, how they connect

- **TUI ↔ loop** — calls `run_command` / `run_for_voice`; shares state
  only via `_pipeline` + the `cancel_event`.
- **loop ↔ tools** — tools registered once on the cached `Agent`;
  `agent.iter` invokes them; `_run_via_iter` inspects results.
- **tools ↔ skills** — code skills register tools; playbook skills are
  surfaced through the `skill` tool.
- **tools ↔ plugins** — TTS/STT/vision tools delegate to plugin
  backends; MCP re-exports remote tools; `send_message` routes via the
  `_BRIDGES` registry.
- **loop ↔ Deep Think** — `propose_deep_think_task` queues a board
  card; `switch_model` swaps to the coder model; `run_deep_think`
  drives `run_command` to build the skill.

## What's wrong — the rebuild targets

1. **`_pipeline` global is the central coupling problem.** A
   module-level `dict[str, Any]` is the de-facto app context; every
   layer imports `jaeger_os.main` to reach it. `LlamaCppModel.request`
   (a "core" module) writes back into `main._pipeline` — a circular
   dependency surviving only on lazy imports. No typing, no owner, no
   lifecycle.
2. **`run_command` vs `run_for_voice` are ~95% duplicated** and have
   drifted (latency reporting only in one). Should be one turn
   function + a thin output adapter.
3. **Three layered loop wrappers** with interleaved concerns;
   `_run_with_fix_loop`'s `for _ in range(max_retries=1)` always runs
   exactly once — theatrical.
4. **`SKIP_FINAL_TOOLS` is a misnamed hand-maintained list** — adding a
   tool means editing that set *and* `_DETERMINISTIC_FINAL_TOOLS` *and*
   the 200-line `_format_tool_result_as_answer` if-ladder. Three
   coupled registries. "Is this result terminal / how do I render it"
   should be a property of the tool.
5. **Two parallel tool-scoping systems** in `toolsets.py` — the old
   `CORE`/`load_toolset` (off, the docstring says it *regressed*
   routing) and the newer `LEAN_CORE`/`model_visible`. `load_toolset`
   is still registered — dead surface the model sees.
6. **Dead / duplicated code** — the legacy `cli_loop` plain-text REPL
   (superseded by the TUI; a second slash-command implementation);
   four copies of "walk pydantic-ai messages pairing tool-calls to
   returns" (`_walk_new_messages`, `_iter_tool_returns`, and inside
   both fix-loop detectors).
7. **The goal loop is TUI-only** (`_post_turn_goal_check` lives in
   `app.py`) — a goal never advances in voice / messaging / daemon.
8. **`asyncio.run` per turn** — a fresh event loop spun up/torn down
   every turn inside a lock-holding thread; `_delegate_internal` nests
   another `asyncio.run` from worker threads. The codebase is
   synchronous with `asyncio.run` islands.
9. **`switch_model`'s RAM contract is a footgun** — correctness
   depends on every caller manually nulling its client ref first.
10. **Skill loading is coarse** — every smoke test re-runs as a
    subprocess at each `_get_agent` cache-miss, including on every
    Deep Think model swap.

## Rebuild plan — incremental, tested, never big-bang

The main loop is the heart; a big-bang rewrite is unacceptable risk.
Each step below is a focused, separately-verifiable refactor; the test
suite stays green after each.

- **R1 — Delete dead code.** Remove `cli_loop` + its slash impl; make
  `python -m jaeger_os` default to the TUI. Low risk, clears noise.
- **R2 — One message-walk helper.** Collapse the 4 copies into a
  single `walk_tool_calls()`; rewire the fix-loop detectors onto it.
- **R3 — Unify the turn.** One `_run_turn()`; `run_command` /
  `run_for_voice` become thin output adapters over it.
- **R4 — Tool-result rendering as a tool property.** Replace
  `SKIP_FINAL_TOOLS` + `_DETERMINISTIC_FINAL_TOOLS` + the 200-line
  ladder with per-tool metadata (terminal? formatter?).
- **R5 — One tool-scoping system.** Delete the old `CORE`/`load_toolset`
  path; keep `LEAN_CORE`/`model_visible`.
- **R6 — Collapse the loop wrappers.** `_run_with_fix_loop` +
  `_run_via_iter` → one clearly-staged turn runner.
- **R7 — Typed run context.** Replace the `_pipeline` dict with an
  explicit, typed `RunContext` passed in — the deepest change, done
  last, behind a shim so it can land gradually.
- **R8 — Goal loop out of the TUI** so it works in every entry point.

R1–R2 are safe cleanups. R3–R6 are the real loop rebuild. R7 is the
architectural fix and the highest-risk — staged last.
