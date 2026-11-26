# JaegerAI Modular Architecture Stack

JaegerAI separates every concern into an independently testable standalone package under `packages/`:

## Python Packages (29)

- **Contracts & Core Spine:** `jaeger-contracts` (incl. `EmbodimentPort`), `jaeger-events`, `jaeger-reliability`, `jaeger-models`
- **Authority & Integrations:** `jaeger-authority` (PolicyEngine, Seatbelt profiles, Hermes secret redaction), `jaeger-skills` (Skills Guard AST auditor, 3-way merge), `jaeger-mcp` (LiveMCPManager with hot-reload), `jaeger-checkpoints`, `jaeger-tools`, `jaeger-lsp`, `jaeger-macos`
- **Cognition, Memory & Orchestration:** `jaeger-cognition` (`WorldModelStore`, 24/7 `CognitiveLifeLoop`, `IdentityStore`), `jaeger-memory` (Memory 2.0 cascading forget, multi-day goals, ephemeral statusbar), `jaeger-loop`, `jaeger-orchestration` (durable SQLite Pregel + time-travel fork, `safe_expr`, `DryRunSimulator`, 32 GB `ResourceGovernor`)
- **Business & Media Studio:** `jaeger-business` (8-role team, spend ledger, approval gates), `jaeger-youtube` (32 GB phased research, episode studio, OpenTimelineIO `.otio` export, `MediaArchiveStore`), `jaeger-channels`
- **24/7 Presence, Voice, Vision & Embodiment:** `jaeger-avatar`, `jaeger-kokoro-tts` (Apple Silicon MLX + `lip_marks()`), `jaeger-whisper-stt` (`hearing.py`), `jaeger-realtime` (`<ignore>/<reply>` gate, barge-in, `FullDuplexVoiceBridge`), `jaeger-vision` (`RollingFrameBuffer`), `jaeger-droid` (`HostDroidEmbodiment` for connected gimbal cameras/mics/speakers), `jaeger-embodiment-minecraft` (headless Mineflayer + Voyager MIT control primitives + `MinecraftSkillLibrary`), `jaeger-hardware` (JP01 bracket protocol + `EStopLatch`)
- **Evals, Protocols & Gateway:** `jaeger-evals` (`SpanTree`, compaction verifier), `jaeger-protocols` (`AG-UI`, `A2UI`, `ACP`), `jaeger-gateway`

## React 19 / TypeScript Packages (5)

- `@jaeger/ui-protocol` — Versioned event envelope, `SeqCursor`, SSE decoder, session reducer
- `@jaeger/ui-sdk` — Write-ahead `SessionStore`, `HttpSseTransport`, `StreamingDeltaBatcher`
- `@jaeger/ui-kit` — Pure `--jg-*` theme tokens, OpenCode `patchmark` streaming Markdown, `StudioTimeline`, `ContextXrayBar`, `CommandPalette` (`Cmd+K`)
- `@jaeger/ui-avatar` — Studio 2D/3D VRM 0.x/1.0 avatar stage (3-point lighting, relaxed stance, AutoBlink, eye saccades, Kokoro viseme lip-sync)
- `@jaeger/ui-features` — Unified 5-Tab Studio UI (`Command`, `Work & Studio`, `Team & Tools`, `Memory & Life`, `Control & Body`) + dockable Live Watch & VR Avatar drawer
