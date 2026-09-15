# ARES Migration

Copies state out of an older ARES install into Jaeger, without deleting or
altering the ARES side. Used once when moving over; safe to re-run.

| File | What it does |
| :--- | :--- |
| `service.py` | Reads ARES state, writes the Jaeger equivalent, records a manifest so a run can be inspected or undone. |
| `tools.py` | Lets the agent run a migration on request. |

**Turn it on:** nothing to enable — it runs when asked.
`JAEGER_ARES_BACKUP_MANIFEST` points at the manifest file if you want it
somewhere specific.

**Check it works:** the migration returns a report listing what moved. Nothing
is removed from ARES, so a failed run costs you nothing.

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
