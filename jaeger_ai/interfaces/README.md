# interfaces/ — Jaeger AI user interfaces and transports

These are application surfaces. They present Jaeger AI, while JaegerOS and
JaegerAgent remain framework dependencies.

| Area | Responsibility |
|---|---|
| [swift/](swift/) | Native macOS app, menu bar, chat, avatar windows, and multimodal launcher |
| [pyside6/](pyside6/) | Qt windows, settings, tray helpers, and shared desktop branding |
| [pyside6/multimodal/](pyside6/multimodal/) | Attached text/audio/video face and explicit standalone development mode |
| [tui/](tui/) | Terminal interface reached through the `jaeger` command |
| [avatar/](avatar/), [avatar_chat/](avatar_chat/), [avatar_player/](avatar_player/) | Avatar rendering, conversation, and playback surfaces |
| [bridge.py](bridge.py) | NDJSON bridge and attached multimodal session transport |
| [client.py](client.py), [mcp_server.py](mcp_server.py) | Python bridge client and MCP transport |

## Ownership and verification

Opening an attached multimodal window must not create a second agent, model,
or memory store. The bridge hosts the runtime; the face handles device capture
and presentation. Standalone mode is an explicit development/benchmark option,
not the desktop application's default.

Shared model ownership does not yet establish identical end-to-end behavior
for every front door. The [0.12.0 release evidence](../../dev/docs/releases/0.12.0/)
tracks remaining routing and live-device gaps. Do not treat a UI mock test as
proof of microphone, camera, or acoustic duplex operation.

Tests live under [dev/tests/jaeger_ai/interfaces/](../../dev/tests/jaeger_ai/interfaces/).
Run the affected tests and an interactive check when changing a surface.
