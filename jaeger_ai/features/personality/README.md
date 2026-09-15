# Personality

The structured persona the agent composes into its system prompt on **every**
turn — so this folder shapes how Jaeger talks all the time, not occasionally.

Traits are modelled on five dimensions, including HEXACO personality factors and
a Fallout-style SPECIAL stat block chosen because it is easier to reason about
than raw numbers.

| File | What it does |
| :--- | :--- |
| `schema.py` | The shape of a persona — the dimensions and their ranges. |
| `character.py` | Loading a named character. |
| `compose.py` | Turning a persona into the text the model actually reads. |
| `persona_state.py` | Mood and state that shift during a conversation. |
| `characters/` | The personas themselves, as editable YAML plus card art. |

**Turn it on:** always on. Pick a character in your instance settings.

**Edit a persona without coding:** open the YAML under `characters/<name>/`.

**Check it works:** change a trait, start a new chat, and the tone shifts.

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
