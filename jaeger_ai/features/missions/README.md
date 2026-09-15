# Missions

Longer-running goals that outlive a single conversation. A mission records what
you asked for, what has been done, and what is left, so work survives a restart.

| File | What it does |
| :--- | :--- |
| `service.py` | Creates, updates, completes and lists missions. |
| `tools.py` | The mission tools the agent can call. |

**Turn it on:** always on.

**Check it works:** ask for your open missions. The list survives quitting and
reopening Jaeger — that persistence is the whole point of the feature.

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
