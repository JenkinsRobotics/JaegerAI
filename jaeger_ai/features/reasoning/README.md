# Reasoning (experimental)

An experimental cognitive loop that runs **on its own clock**, driven by Jaeger's
heartbeat rather than by you sending a message.

That is what separates it from every other "thinking" code in the tree: the
normal agent loop reasons about one user turn and stops. This keeps perceiving
and forming intentions between turns.

Experimental — it is off unless deliberately enabled, and the rest of Jaeger
works without it.

| File | What it does |
| :--- | :--- |
| `engine.py` | The loop that runs on each heartbeat tick. |
| `perception.py` | What the agent notices between turns. |
| `belief.py` | What it currently holds to be true. |
| `intent.py` | What it decides it wants to do next. |
| `learning.py` | How beliefs update from what happened. |

**Turn it on:** enabled per instance; off by default.

**Check it works:** with it running, the agent acts between your messages. If
nothing happens when you are idle, it is off.

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
