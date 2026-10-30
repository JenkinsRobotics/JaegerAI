# Goals

Operator-declared goals and projects that outlive a single conversation, with
goal-aligned tool access.

| File | What it does |
| :--- | :--- |
| `service.py` | Creates, updates, lists, and rolls up goals/projects over the durable commitment store. |
| `tools.py` | The goal tools the agent can call (`goal_*`, `project_status`, `task_spawn`). |
| `README.md` | This file. |

**Turn it on:** always on.

**How tool access works:** a goal declares a `tool_bundle` (defined once in
`jaeger_ai/contract/tool_bundles.py`). The Gateway intersects that bundle
with the assigned agent's enforced allowlist at turn admission — a bundle is
a **cap, not a grant**. A CHARACTER agent (enforced no-tools) stays at zero
no matter what bundle a goal declares.

**Check it works:** ask for your open goals. The list survives quitting and
reopening Jaeger — that persistence is the whole point of the feature.

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
