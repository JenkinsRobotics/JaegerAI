# Knowledge Library

A folder of notes and documents the agent can search and add to. Plain files on
disk, not a database, so you can open and edit them yourself.

| File | What it does |
| :--- | :--- |
| `store.py` | Reads, writes, indexes and searches the folder. |
| `tools.py` | The note and document tools the agent can call. |

**Turn it on:** always on; it points at your library folder in instance settings.

**Check it works:** ask the agent to save a note, then look for the file in your
library folder — it is just a file.

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
