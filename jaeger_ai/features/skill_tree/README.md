# Skill Tree

Tracks the agent's skills as a graph, awarding XP when a tool is used and
unlocking dependent skills as prerequisites are met — a game-style progression
over the agent's real capabilities.

| File | What it does |
| :--- | :--- |
| `schema.py` | What a skill node is and how nodes connect. |
| `registry.py` | The live graph: look up, award XP, apply level-ups. |
| `seed.py` | The starting set of skills. |
| `xp_emitter.py` | Turns tool calls into XP awards. |

**Turn it on:** always on; it records as tools get used.

**Check it works:** use a tool repeatedly and its node gains XP. Design notes are
in `dev/docs/skills/SKILL_TREE.md`.

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
