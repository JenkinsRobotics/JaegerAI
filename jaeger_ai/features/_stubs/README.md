# _stubs

Backward-compatibility stubs for features archived in v0.13.0. Each stub
re-exports the old import path and raises a clear deprecation error pointing
at the migration guide in `docs/migration/`.

| File | What it does |
| :--- | :--- |
| `shared_memory.py` | Deprecated stub for the archived `shared_memory` feature. |

**Turn it on:** always on (import-safe no-ops; they only fire if legacy code imports the old path).

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
