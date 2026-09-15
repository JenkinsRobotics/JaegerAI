# History Import

Imports past conversations from other tools — ARES, Claude, Codex, Gemini and
Grok — so previous work is searchable inside Jaeger.

| File | What it does |
| :--- | :--- |
| `parsing.py` | Understands each tool's export format. |
| `contracts.py` | The shared shape every import is converted into. |
| `service.py` | Runs an import and returns an `ImportReport`. |
| `tools.py` | Lets the agent import on request. |

**Turn it on:** point it at an export folder. Nothing is enabled permanently.

**Check it works:** the `ImportReport` counts conversations found, imported and
skipped. Re-importing the same export does not duplicate anything.

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
