# JaegerOS — native macOS desktop app

> The 0.3.0 Apple-native rebuild of the JROS client surface.
> Replaces the rumps + Terminal-spawn tray that 0.2.6 retired.

A single Swift process owns the tray icon, the chat window, the pill
launcher, and the voice loop. Talks to the Python `jaeger_os` daemon
over the existing Unix socket using `chat.send` / `chat.subscribe`.

## Status

Week 0 scaffold — `MenuBarExtra` only, no daemon connection yet.

| Week | Lands | Status |
|------|-------|--------|
| 0 | `MenuBarExtra` skeleton, About / Quit | ✅ this commit |
| 1 | Unix-socket daemon client + NDJSON protocol layer | next |
| 2 | SwiftUI chat window (bubbles, composer, status bar) | |
| 3 | Pill launcher + Option+Space global hotkey | |
| 4 | AVAudioEngine voice loop (push-to-talk + voice processing AEC) | |
| 5 | CoreML-accelerated `whisper.cpp` STT; AVSpeechSynthesizer TTS | |
| 6 | Polish, side-panel sketches, `.app` packaging | |

## Build & run from the command line

```bash
cd apps/JaegerOS
swift build -c debug
swift run JaegerOS
```

The app should appear in your menu bar with a brain icon labeled "JROS."
There's no Dock icon yet (that comes when we add the `LSUIElement = true`
Info.plist via Xcode).

## Open in Xcode

```bash
cd apps/JaegerOS
xed Package.swift          # opens in Xcode, autogenerates project
```

Xcode reads `Package.swift` and synthesizes the project. Use the
auto-generated scheme to build, run, and debug interactively. When we
need an `.xcodeproj` for code signing + bundling, we'll convert this
SwiftPM package to a full Xcode project (File → New → Project from
Package, or generate via xcodegen).

## Architecture (target end-state for 0.3.0)

```
┌────────────────────────────────────────────────┐
│           JaegerOS.app (this package)          │
│   ┌────────────────────────────────────────┐   │
│   │ MenuBarExtra — NSStatusItem            │   │
│   │   Open Chat · Open Pill · Quit         │   │
│   ├────────────────────────────────────────┤   │
│   │ Chat window (SwiftUI)                  │   │
│   │   Bubbles · composer · status bar      │   │
│   ├────────────────────────────────────────┤   │
│   │ Pill launcher (Option+Space)           │   │
│   │   Frameless, always-on-top, autohides  │   │
│   ├────────────────────────────────────────┤   │
│   │ Voice loop                             │   │
│   │   AVAudioEngine (built-in AEC)         │   │
│   │   CoreML Whisper STT (ANE-accelerated) │   │
│   │   AVSpeechSynthesizer (placeholder TTS)│   │
│   ├────────────────────────────────────────┤   │
│   │ DaemonClient                           │   │
│   │   Unix socket → NDJSON protocol        │   │
│   │   chat.send · chat.subscribe · status  │   │
│   └────────────────────────────────────────┘   │
└────────────────────────────────────────────────┘
                          │
                          │ <instance>/run/jaeger.sock
                          ▼
┌────────────────────────────────────────────────┐
│   jaeger_os daemon (Python, unchanged)         │
│   Gemma + memory + tools + kanban + skills     │
└────────────────────────────────────────────────┘
```

## Why Swift (not PySide 6 / Tauri / Electron)

See `dev_docs/odysseus_review_and_0.3.0_plan.md` § 1.1 for the full
rationale. Short version:

- Smallest footprint (~10 MB binary, ~40 MB RAM idle)
- Direct ANE access for CoreML-accelerated Whisper (2-3× faster STT)
- AVAudioEngine retires PortAudio's wedging-CoreAudio bug class
- AVAudioEngine voice processing mode = free AEC (retires speexdsp)
- Native AirPods / Bluetooth route handling
- Apple is JROS's bread and butter — Jetson on JP01 is a sensor + motor
  I/O node, not a brain target

## References

- `dev_docs/odysseus_review_and_0.3.0_plan.md` — full 0.3.x release ladder
- Hermes' `ui-tui` (React+Ink) — streaming token deltas, tool/reasoning
  display, modal overlays as state branches
- Lilith's `tray.py` PyQt6 pill — visual language (16px rounded, blue
  accents, glass), Option+Space global hotkey pattern
- [Ollama Desktop](https://github.com/ollama/ollama) — same architectural
  shape (Swift UI + separate backend daemon over localhost)
