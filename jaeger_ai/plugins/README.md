# plugins/ — drop-in external integrations

This directory holds **plugins** under the strict vocabulary defined in
[../../docs/VOCABULARY.md](../../docs/VOCABULARY.md): each subdirectory is a
self-contained module bridging the agent to a specific external service or
capability.

## What lives here

| Plugin | What it bridges to |
|---|---|
| `discord/` | Discord bot DMs + @mentions via `discord.py` |
| `telegram/` | Telegram chats via `python-telegram-bot` |
| `imessage/` | macOS Messages via chat.db polling + AppleScript |
| `mcp/` | external MCP server processes (Model Context Protocol) |
| `messaging_gateway.py` | top-level daemon that orchestrates the three messaging plugins |

Future candidates:

- `kokoro_tts/` — speaker output via Kokoro TTS (currently in `core/tools/speak.py`; will migrate)
- `whisper_stt/` — mic capture + wake word + transcription
- `realsense/` — RealSense D435 perception
- `yolo/` — object classification
- `github/`, `slack/`, `calendar/`, etc.

## What does NOT live here

- **`thinking_runner`** — that's a Runner (framework-internal background work), not an external integration. Lives in `agent/background/thinking_runner.py`.
- **`cron_runner`** — same reason. Lives in `agent/background/cron_runner.py`.
- **Tools that ship with the framework** — atomic LLM-callable functions live in `agent/tools/`.
- **Skills** (novel composite capabilities — authored, learned, or trained) — live in `skills/` (framework zone) or `<instance>/skills/` (instance zone).

See [docs/VOCABULARY.md](../../docs/VOCABULARY.md) for the full decision tree.

## Anatomy of a plugin

A plugin directory should contain:

```
plugins/<name>/
├── plugin.yaml           ← manifest: deps, env vars, registered bridges/tools
├── <module>.py           ← implementation (lazy-imports heavy deps)
├── __init__.py           ← exposes the public class(es)
└── tests/smoke_test.py   ← importability check
```

### `plugin.yaml` shape

```yaml
name: discord
version: 1
description: |
  Bidirectional Discord adapter. Listens for DMs from allowlisted users;
  lets the agent push proactive messages via send_message().
requires:
  libraries: [discord.py]
  env: [DISCORD_BOT_TOKEN]
  env_optional: [DISCORD_ALLOWED_USER_IDS]
  hardware: []          # microphone / speaker / camera / etc.
  platform: []          # [darwin] for macOS-only plugins
registers_bridges: [discord]   # entries in the shared bridge registry
registers_tools: []            # additional agent-callable tools (if any)
capabilities: []               # [ssml, emotion, voice_clone, …] for capability discovery
```

### Smoke test
Must pass before the plugin's tools are registered with the agent. Should
verify **importability without external SDKs installed** — the plugin's
heavy library imports should be deferred to `start()`, not at module load.

### Bridge registry
Plugins that maintain a long-lived inbound + outbound connection (Discord,
Telegram, iMessage) register themselves with the shared registry in
[`__init__.py`](__init__.py):

```python
from .. import register_bridge, deregister_bridge

class MyBridge:
    def start(self) -> None:
        # ...connect...
        register_bridge("my_channel", self)

    def stop(self) -> None:
        deregister_bridge("my_channel")
```

The agent's `send_message(channel, recipient, text)` tool reads from this
registry to route outbound messages, so any plugin that registers becomes
addressable from the agent without further wiring.

## Adding a new plugin

1. Create `plugins/<name>/` with the four files above.
2. If the plugin maintains a bridge, call `register_bridge` from `start()`.
3. If it registers new agent tools, wire them in `jaeger_os/main.py`
   alongside `send_message` (or have the plugin call `agent.tool_plain`
   directly during init — TBD as auto-discovery lands).
4. Add the plugin's CLI flag (e.g. `--with-mcp`) and `init_extensions`
   branch in `main.py` if it's opt-in at framework startup.
5. Document the plugin in [../../docs/PYTHON_JAEGER.md](../../docs/PYTHON_JAEGER.md).

## Future: separate-process plugins

Today every plugin runs in-process. When we deploy to robot hardware
(Jetson + Mac), some plugins will graduate to separate-process daemons
running over a transport (ZMQ, gRPC). The `plugin.yaml` manifest will
declare its runtime mode:

```yaml
runtime: in_process | separate_process
transport: zmq      # only when runtime: separate_process
```

The plugin's source code structure stays the same; only the runtime
topology changes. See VOCABULARY.md → "Plugin is a deployment endpoint,
not a structural fork" for the rationale.
