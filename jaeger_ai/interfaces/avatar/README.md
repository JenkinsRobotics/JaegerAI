# JaegerAI-Avatar

Mac-native renderer for the JaegerAI animation node.  Ships with the
framework — JaegerAI Python publishes animation frames on a WebSocket,
this Swift app displays them.

## Status

**Phase 1 scaffold (2026-06-08)** — window + WebSocket plumbing +
placeholder rendering.  Mochi adapters integrate phase by phase.
See `dev/docs/avatar/0.5.0_swift_renderer_plan.md` for the roadmap.

## Build + run (Phase 1)

```bash
cd jaeger_os/interfaces/avatar
swift build
swift run JaegerAIAvatar
```

Opens a window with a placeholder canvas + connection status.
Set the JaegerAI frame stream URL via the **Connect** field
(default `ws://127.0.0.1:8765/frames`).

## Architecture

```
JaegerAI Python brain
  └─ AnimationNode
       └─ frame_callback → WebSocketBridge → ws://.../frames
                                                    │
                                                    ▼
                                          JaegerAI-Avatar (this app)
                                          - WebSocketClient
                                          - FrameDecoder
                                          - RendererView
```

Frame protocol: each WebSocket binary message is
`[4-byte length][JSON header][raw RGBA bytes]`.  Details in
`dev/docs/avatar/0.5.0_swift_renderer_plan.md`.

## Tests

```bash
swift test
```

Currently exercises the FrameDecoder round-trip.  Visual tests
are manual until Phase 2.
