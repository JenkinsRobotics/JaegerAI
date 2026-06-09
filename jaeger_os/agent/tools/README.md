# core/tools/ — built-in tools (atomic functions, organized by category)

This is the framework's primitive tool surface. **Tools are individual
Python functions**, grouped into category files (one `.py` per category)
and registered onto the agent via `@agent.tool_plain` from main.py.

This is intentionally NOT a "skills" folder. Skills (the v2-contract
versioned-folder kind) live at the framework root in [`../../skills/`](../../skills/)
and at runtime in `instance/<name>/skills/`.

## How to add a new tool

Add a function to the appropriate category file:

```python
# core/tools/web.py  (for a new web-related primitive)
def my_new_tool(arg: str) -> dict[str, Any]:
    """Short one-line docstring — this is what the LLM sees."""
    ...
    return {"result": ...}
```

Re-export it from [`__init__.py`](__init__.py) so callers can do
`from jaeger_os.agent.tools import my_new_tool`, then wire it onto
the agent in `jaeger_os/main.py`:

```python
@agent.tool_plain
def my_new_tool(arg: str) -> dict:
    """Same docstring — the LLM sees THIS one."""
    return t.my_new_tool(arg=arg)
```

If the result dict IS the user-facing answer (no need for an LLM
rewrite), add the tool name to `SKIP_FINAL_TOOLS` in main.py and
provide a one-line formatter in `_format_tool_result_as_answer`.

## Category files

| file | tools |
|---|---|
| `_common.py` | shared infra: `bind()`, audit log, sandbox resolver, git autocommit |
| `time_and_math.py` | `get_time`, `calculate`, `system_status` |
| `files.py` | `file_write`, `edit_file`, `append_file`, `delete_file`, `file_read`, `list_skill_dir`, `search_files` (sandboxed to skills/) |
| `memory.py` | `remember`, `recall`, `forget`, `list_facts`, `search_memory` |
| `scheduling.py` | `schedule_prompt`, `list_schedules`, `cancel_schedule` |
| `web.py` | `web_search`, `web_fetch`, `get_weather` |
| `code.py` | `run_python`, `run_shell` (sandboxed subprocess) |
| `speak.py` | `speak` (literal text or workspace file), `warm_kokoro` (Kokoro TTS) |
| `vision.py` | `look_at`, `generate_image` (Moondream2 + SDXL-Turbo) |
| `host.py` | `open_on_host` (macOS: URL / file / app) |
| `credentials.py` | `get_credential`, `list_credentials` |
| `delegation.py` | `ask_user`, `help_me` |

Plus `delegate` lives in `main.py` (needs recursion access).

## Tools vs. Skills — what's the difference?

| | Tools (here) | Skills (`../../skills/` and `instance/<name>/skills/`) |
|---|---|---|
| Shape | One `def` in a category `.py` file | A folder `<name>_v<N>/` with `SKILL.md` + module + smoke test |
| Granularity | Atomic primitive (one capability per function) | Higher-order package (can compose multiple tools + helpers) |
| Who writes them | Framework maintainers | Framework maintainers OR the agent itself (at runtime) |
| Lifecycle | Loaded at process start, fixed | Discovered by the skill loader; supports versioned override |
| Use case | Built-in stable capabilities (time, files, web) | Composable, replaceable, learnable behavior packages |

Rule of thumb: if it's a single short Python function with one clear
purpose, it's a tool. If it has its own docs + tests + might be replaced
later by a versioned override, it's a skill.
