# Hermes Contributor Quick Reference

For occasional contributors and PR authors. Full developer docs:
https://hermes-agent.nousresearch.com/docs/developer-guide/ . Use the JROS
`terminal` tool to run commands and `read_file`/`patch` to edit source.

## Project Layout

```
hermes-agent/
├── run_agent.py          # AIAgent — core conversation loop
├── model_tools.py        # Tool discovery and dispatch
├── toolsets.py           # Toolset definitions (TOOLSETS, _HERMES_CORE_TOOLS)
├── cli.py                # Interactive CLI (HermesCLI)
├── hermes_state.py       # SQLite session store
├── agent/                # Prompt builder, compression, memory, routing, credential pooling, skill dispatch
├── hermes_cli/           # CLI subcommands, config, setup
│   ├── commands.py       # Slash command registry (CommandDef)
│   ├── config.py         # DEFAULT_CONFIG, env var definitions
│   └── main.py           # CLI entry point + argparse
├── tools/                # One file per tool
│   └── registry.py       # Central tool registry
├── gateway/              # Messaging gateway
│   └── platforms/        # Platform adapters (telegram, discord, …)
├── cron/                 # Job scheduler
├── tests/                # ~3000 pytest tests
└── website/              # Docusaurus docs
```

## Adding a Tool

1. Create `tools/your_tool.py` with a top-level `registry.register(...)` call
   (auto-discovered on import — no manual list needed):
```python
import json, os
from tools.registry import registry

def check_requirements() -> bool:
    return bool(os.getenv("EXAMPLE_API_KEY"))

def example_tool(param: str, task_id: str = None) -> str:
    return json.dumps({"success": True, "data": "..."})

registry.register(
    name="example_tool",
    toolset="example",
    schema={"name": "example_tool", "description": "...", "parameters": {...}},
    handler=lambda args, **kw: example_tool(param=args.get("param", ""), task_id=kw.get("task_id")),
    check_fn=check_requirements,
    requires_env=["EXAMPLE_API_KEY"],
)
```
2. Add the toolset to `_HERMES_CORE_TOOLS` in `toolsets.py` if it should be default.

All handlers return JSON strings. Use `get_hermes_home()` for paths — never
hardcode `~/.hermes`. New tools need a `check_fn` so they only appear when
requirements are met.

## Adding a Slash Command

1. Add a `CommandDef` to `COMMAND_REGISTRY` in `hermes_cli/commands.py`
2. Add a handler in `cli.py` → `process_command()`
3. (Optional) gateway handler in `gateway/run.py`

All consumers (help, autocomplete, Telegram menu, Slack mapping) derive from the
central registry automatically.

## Agent Loop (high level)

```
run_conversation():
  1. Build system prompt
  2. Loop while iterations < max:
     a. Call LLM (OpenAI-format messages + tool schemas)
     b. tool_calls → dispatch each via handle_function_call() → append results → continue
     c. text response → return
  3. Context compression triggers automatically near the token limit
```

## Testing

```bash
python -m pytest tests/ -o 'addopts=' -q   # full suite
python -m pytest tests/tools/ -q            # specific area
```
- Tests auto-redirect `HERMES_HOME` to temp dirs — never touch real `~/.hermes/`.
- Run the full suite before pushing.
- Use `-o 'addopts='` to clear baked-in pytest flags.

### Windows testing
`scripts/run_tests.sh` assumes POSIX venvs (`.venv/bin/activate`) and errors on
Windows (`venv/Scripts/`), whose installed venv also has no pip/pytest (stripped).
Workaround: install pytest into a system Python 3.11 user site, then run directly:
```bash
"/c/Program Files/Python311/python" -m pip install --user pytest pytest-xdist pyyaml
export PYTHONPATH="$(pwd)"
"/c/Program Files/Python311/python" -m pytest tests/tools/test_foo.py -v --tb=short -n 0
```
Use `-n 0` (not `-n 4`) — `pyproject.toml`'s `addopts` already includes `-n`.

### Cross-platform test guards
POSIX-only tests need skip markers:
- Symlinks → `@pytest.mark.skipif(sys.platform == "win32", ...)`
- POSIX file modes (0o600) → `@pytest.mark.skipif(sys.platform.startswith("win"), ...)`
- `signal.SIGALRM` → Unix-only (`tests/conftest.py::_enforce_test_timeout`)
- Windows regressions → `@pytest.mark.skipif(sys.platform != "win32", ...)`

Monkeypatching `sys.platform` alone is NOT enough when code also calls
`platform.system()` / `platform.release()` / `platform.mac_ver()` (they re-read
the real OS). Patch all together:
```python
monkeypatch.setattr(sys, "platform", "linux")
monkeypatch.setattr(platform, "system", lambda: "Linux")
monkeypatch.setattr(platform, "release", lambda: "6.8.0-generic")
```
See `tests/agent/test_prompt_builder.py::TestEnvironmentHints`.

## Environment-hints block (prompt authoring)

Host OS / home / cwd / terminal-backend / shell guidance is emitted from
`agent/prompt_builder.py::build_environment_hints()`. Local backend → emit host
info + Windows notes. Remote backends (`docker, singularity, modal, daytona, ssh,
vercel_sandbox, managed_modal`) → SUPPRESS host info; a live probe runs inside the
backend (cached in `_BACKEND_PROBE_CACHE`). Key fact: when `TERMINAL_ENV !=
"local"`, EVERY file tool (`read_file`, `write_file`, `patch`, `search_files`)
runs inside the backend container, not the host — never describe the host then.

## Commit Conventions

```
type: concise subject line

Optional body.
```
Types: `fix:`, `feat:`, `refactor:`, `docs:`, `chore:`.

## Key Rules

- Never break prompt caching — don't change context, tools, or system prompt
  mid-conversation.
- Message role alternation — never two assistant or two user messages in a row.
- Use `get_hermes_home()` from `hermes_constants` for all paths (profile-safe).
- Config values → `config.yaml`; secrets → `.env`.
- New tools need a `check_fn`.
