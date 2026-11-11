# CLI Backends

Finds other agent CLIs already installed on your machine and offers them as
models you can pick, exactly like a cloud model in the dropdown.

The distinction that matters: a CLI backend is a **brain**, not a worker. Jaeger
keeps the conversation, the tools, the memory and the permission prompts, and
only asks the other CLI to produce text. (Handing a whole job to another agent is
`delegate_task`, which is a different thing.)

| File | What it does |
| :--- | :--- |
| `discovery.py` | Looks along `PATH` for known CLIs and reports which are installed. |
| `service.py` | Runs the chosen CLI as a model and returns its answer. |

**Turn it on:** install a supported CLI and sign in the way that CLI expects
(browser / subscription login — not Jaeger API keys). It appears in the model
list by itself.

Supported subscription-style brains today:

| CLI | Binary | Auth |
| :--- | :--- | :--- |
| Claude Code | `claude` | `claude` → `/login` |
| OpenAI Codex / ChatGPT | `codex` | `codex login` (ChatGPT subscription) |
| Grok | `grok` | Grok account / key the CLI already uses |
| Gemini CLI | `gemini` | browser Google sign-in under `~/.gemini` |
| Antigravity | `agy` | browser Google sign-in / OS keyring |
| Hermes | `hermes` | whatever that CLI is already signed into |

**Check it works:** open the model picker — a discovered CLI is listed there.
Pick `cli:agy` (or `cli:gemini` / `cli:codex`) to burn your existing
subscription quota instead of a separate API key.

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
