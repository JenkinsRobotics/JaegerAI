# Calendar (CalDAV)

Talks to any standards-compliant calendar server (iCloud, Fastmail, Nextcloud,
Radicale) so the agent can read your schedule and create events.

| File | What it does |
| :--- | :--- |
| `service.py` | Connects to the server, caches events locally, creates and deletes them. |
| `tools.py` | The calendar tools the agent can call. |

**Turn it on:** run the `configure` step with your server URL and credentials;
they are stored with the rest of your instance settings, not in this folder.

**Check it works:** ask the agent what is on your calendar today. A wrong URL or
password surfaces as a `CalDavError` naming which one failed.

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
