# Timeline

Multi-track scheduling for agent "performances" — lining up speech, animation and
actions on parallel tracks with clips at set times, like a video editor.

Used mainly by the avatar. If you are not using the avatar, nothing here runs.

| File | What it does |
| :--- | :--- |
| `schema.py` | `Timeline`, `TimelineTrack` and `TimelineClip`, plus load and save. |
| `runner.py` | Plays a timeline, firing each clip at its moment. |

**Turn it on:** nothing to enable; a timeline runs when something plays one.

**Check it works:** load a timeline and play it — clips fire in order. Schema
notes are in `dev/docs/avatar/0.5.0_timeline_schema.md`.

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
