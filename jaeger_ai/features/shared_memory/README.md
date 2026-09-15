# Shared Memory

Optional shared memory across several agents, backed by [Honcho], so two agents
can remember the same facts about you.

| File | What it does |
| :--- | :--- |
| `honcho_client.py` | Talks to the Honcho service. |

**Turn it on:** set `HONCHO_API_KEY` and `HONCHO_WORKSPACE` (plus `HONCHO_URL`
for a self-hosted server). Unset, Jaeger uses its own local memory and this
folder does nothing.

**Check it works:** tell one agent a fact and ask another about it.

[Honcho]: https://honcho.dev

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
