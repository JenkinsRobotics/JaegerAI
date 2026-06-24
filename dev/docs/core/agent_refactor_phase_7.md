# Phase 7 — Hermes-style toolsets

**Status:** Phase 7.1 shipped (group definitions + agent-loop filter + boot-time env-var wiring).

## What landed

A first-class **toolsets** system that bundles related tools and lets
the agent loop expose only the active groups to the model — the
Hermes pattern that keeps per-turn schema cost down by 50-90%.

### Files added

| File | Purpose |
|---|---|
| [src/jaeger_os/agent/toolsets.py](../src/jaeger_os/agent/toolsets.py) | `JAEGER_TOOLSETS` map (atomic + composite), `resolve_toolsets`, `list_toolsets`, `toolset_for_tool` |
| [tests/jaeger_os/agent/test_agent_toolsets.py](../tests/jaeger_os/agent/test_agent_toolsets.py) | 18 tests pinning the data model, resolver, reverse lookup, and `JaegerAgent` filter wiring |

### Files modified

| File | Change |
|---|---|
| [src/jaeger_os/agent/jaeger_agent.py](../src/jaeger_os/agent/jaeger_agent.py) | New `toolsets: set[str] | None` constructor arg; resolves to a tool-name set at construction time |
| [src/jaeger_os/agent/runtime_bridge.py](../src/jaeger_os/agent/runtime_bridge.py) | `build_jaeger_agent` passes `toolsets` through to `JaegerAgent` |
| [src/jaeger_os/main.py](../src/jaeger_os/main.py) | `_pipeline["toolsets"]` slot + `_parse_toolsets_env()` parser; threaded through `delegate_task`, `prewarm`, and `_run_turn_via_jaeger_agent` |

### How to use

Set the env var before booting:

```bash
JAEGER_TOOLSETS=default ./jaeger-os               # cuts schema by 53%
JAEGER_TOOLSETS=essentials,files ./jaeger-os      # cuts by 75%
JAEGER_TOOLSETS=robot ./jaeger-os                 # embodied workload
```

Or in code:

```python
agent = JaegerAgent(
    adapter=LocalLlamaAdapter(model_path="..."),
    toolsets={"default"},
    skip_final_tools=SKIP_FINAL_TOOLS,
)
```

## Toolset catalogue

Atomic toolsets (no composition):

| Name | Tools | Notes |
|---|---|---|
| `time` | get_time | 1 tool — the model's only source of truth for "now" |
| `math` | calculate | |
| `host` | system_status, list_credentials, get_credential | |
| `files` | read_file, write_file, append_file, patch, delete_file, list_skill_dir, search_files | |
| `web` | web_search, web_extract, get_weather | |
| `memory` | memory + remember/recall/forget/list_facts/search_memory siblings + set_name/update_soul | Both umbrella + siblings — A/B candidate |
| `memory_umbrella_only` | memory, set_name, update_soul | Hermes pattern (avoid attractor split) |
| `code` | execute_code, terminal, install_package, list_venv_packages, run_in_venv, start_background, list_background, check_background, stop_background | |
| `schedule` | schedule_prompt, list_schedules, cancel_schedule | |
| `planning` | todo, propose_deep_think_task, list_deep_think_queue | |
| `kanban` | kanban + board_view/add/move/update | Umbrella + siblings |
| `kanban_umbrella_only` | kanban | Hermes pattern |
| `browser` | browser | |
| `skills` | skill, reload_skills, package_skill, benchmark_skill | |
| `media` | text_to_speech, vision_analyze, image_generate, listen | |
| `delegate` | delegate_task, clarify, help_me | |
| `comm` | send_message, list_plugins, setup_plugin | |
| `host_ui` | open_on_host | |
| `computer` | computer_use, computer_do, computer_look, computer_capture, computer_windows, computer_open, computer_click, computer_type, computer_key, computer_menu, computer_screenshot, computer_bg_apps/windows/move/resize/press/js | |
| `computer_umbrella_only` | computer_use, computer_do | Hermes pattern |
| `toolset_mgmt` | load_toolset | Always-on so the model can switch toolsets mid-session |

Composite toolsets (fan out via `includes`):

| Name | Includes | Resolved tool count |
|---|---|---|
| `essentials` | time + math + host + planning + toolset_mgmt | ~9 |
| `default` | essentials + files + web + memory + delegate + schedule | ~33 |
| `default_consolidated` | essentials + files + web + memory_umbrella_only + delegate + schedule | ~28 |
| `developer` | default + code + skills + kanban | ~51 |
| `robot` | essentials + files + media + computer + comm | ~23 |
| `full` | everything | ~63 |

## Measured savings

```
Toolset                        # tools   schema bytes   vs full
------------------------------------------------------------------
(no filter)                          63          36015       100%
default                              33          16961        47%
default_consolidated                 28          14267        40%
essentials                            9           4902        14%
developer                            51          27905        77%
robot                                23          13252        37%
files                                 7           3693        10%
```

At ~4 chars/token, `default` reclaims **~5,000 tokens per turn**.
That's exactly the headroom that was overflowing the 16K context on
L2/L3 turns in the Phase 6 A/B bench.

## Smoke test — routing correctness with `JAEGER_TOOLSETS=default`

10/10 prompts routed correctly with the reduced schema:

```
✓ what time is it                    →  get_time
✓ calculate 47 times 23 plus 12      →  calculate
✓ what is the current weather…       →  get_weather
✓ list the workspace                 →  list_skill_dir
✓ make a file called bench.txt…      →  write_file
✓ delete bench.txt                   →  delete_file
✓ remember that my favorite color…   →  memory
✓ what is my favorite color          →  memory
✓ forget my favorite color           →  memory
✓ tell me a one sentence story…      →  (free text)
```

Compare with the prior L1 bench (unfiltered: 28/34 routing correct).
Notably, the previously-troublesome `remember`/`recall`/`forget`
prompts now route cleanly to the `memory` umbrella because the
sibling tools aren't in the catalogue distracting the model — the
"umbrella vs sibling attractor split" we diagnosed in the Phase-6
A/B is gone.

## Phase 7.2 — open work

These are nice-to-haves we didn't ship in 7.1:

1. **`/toolsets` slash command** — show current active set + available
   toolsets; let the operator switch at runtime without restarting.
2. **Per-session toolset selection** — instead of one global setting,
   per-session pickers (a kanban worker uses `developer`, a voice
   chat uses `essentials`).
3. **`load_toolset` tool** — already in the registry; needs the
   underlying impl to call `_pipeline["toolsets"] = {name}` and
   rebuild `_jaeger_agents_by_session[key]`.
4. **Config-file toolset selection** — `config.yaml: toolsets: [...]`
   so each instance ships its own default without env-var wrangling.
5. **Tool-consolidation audit** — bench `default` vs `default_consolidated`
   and decide whether to permanently drop the memory + kanban siblings.
6. **Composite-toolset cycle detection in tests** — the resolver
   already handles cycles via `visited`, but no test exercises that
   path yet.

## What this does NOT change

- Tool implementations are untouched (no functions deleted)
- Default behaviour (no env var) is **every tool exposed** — same as
  pre-Phase-7, no breakage for code that depends on a tool being
  available
- All 905 existing tests still pass; 18 new tests added
