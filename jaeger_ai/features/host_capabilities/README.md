# Host Capabilities

The tools that let the agent actually touch this Mac — read and write files in
your workspace, run commands, control apps, use the camera, and read and write
memory. Every one of them is permission-checked before it runs.

This is the most security-sensitive folder in the repo. `grants.py` is the gate.

| File | What it does |
| :--- | :--- |
| `grants.py` | Decides whether a tool call is allowed, and what to ask you. |
| `workspace_tools.py` | Files and folders inside your workspace. |
| `system_tools.py` | Shell commands and processes. |
| `mac_tools.py` | macOS apps, notifications, clipboard. |
| `camera_tools.py` | Camera capture. |
| `memory_tools.py` | Long-term memory reads and writes. |
| `server.py` | Serves all of the above as MCP tools. |

**Turn it on:** always on; how much it may do without asking comes from your
instance's permission mode.

**Check it works:** ask the agent to list files in your workspace. If permissions
are set to confirm, you get a prompt first — that is the gate working.

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
