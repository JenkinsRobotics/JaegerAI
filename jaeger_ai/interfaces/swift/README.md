> **Classification:** CURRENT REFERENCE.
> **Current execution entry point:** [`docs/CONTINUE_FROM_HERE.md`](../../../docs/CONTINUE_FROM_HERE.md)

# JaegerAI — native macOS desktop app

> The primary UI since 0.7.0. `JaegerAI.app` is built from this package
> into `~/.jaeger/apps/swift-build/JaegerAI.app` (outside the checkout);
> `jaeger` launches the app, `jaeger --tui` / `jaeger dev` keep the
> terminal first-class. (`launch.py` was removed in 0.7.)

One Swift process owns the tray card, the native chat window, the avatar orb,
the floating pill (⌥Space), and the voice loop. It spawns `jaeger bridge`
(the Python NDJSON stdio child) and speaks **protocol v1**. Safari WebUI at
`jaeger webui url` is a separate browser chat (same agent, different renderer).

## Build, test, run

Build output is always **outside the checkout** at `~/.jaeger/apps/swift-build/JaegerAI.app`
(or `$JAEGER_SWIFT_BUILD/JaegerAI.app`). A pre-existing `interfaces/swift/.build/`
in the repo is left untouched; it is not used by the build script.

```bash
cd jaeger_ai/interfaces/swift
<<<<<<< HEAD
swift test --scratch-path "$HOME/.cache/jaeger/swift-tests" # external test build
Scripts/build-app.sh         # debug  → ~/.jaeger/apps/swift-build/JaegerAI.app
Scripts/build-app.sh --release  # release build (same path)
JAEGER_SWIFT_BUILD=/path/to/dir Scripts/build-app.sh  # custom root
open --env "JAEGER_REPO=$(git rev-parse --show-toplevel)" ~/.jaeger/apps/swift-build/JaegerAI.app
=======
swift build            # debug build
swift test             # ProtocolFixtureTests — the wire contract
Scripts/build-app.sh --dev   # .build/JaegerAI-dev.app (pins the jaeger-dev instance)
Scripts/build-app.sh         # .build/JaegerAI.app (product)
>>>>>>> origin/master
```

`xed Package.swift` opens the package in Xcode.

`Scripts/build-app.sh --print-build-dir` resolves and validates the selected
output without creating directories or starting a build. CLI launchers pass the
checkout through `JAEGER_REPO`; direct Finder launch from an arbitrary checkout
still needs qualification. This is external-build support, not a self-contained
or GUI-qualified release artifact. No installed app is replaced unless the
operator explicitly invokes installation.

## Source layout

One directory per feature; each window follows the same shape — a
`*WindowController` (AppKit lifecycle, lazy creation, single instance)
hosting SwiftUI views over shared `ObservableObject` state. No polling
loops anywhere: state flows through `@Published` (Combine), animation
through `TimelineView` schedules.

```
Sources/JaegerAI/
  JaegerAIApp.swift     @main MenuBarExtra scene (tray icon + card)
  AppDelegate.swift     activation policy, splash boot, orderly quit
  Bridge/               the agent seam — everything else is UI
    Protocol.swift        typed frames, NDJSON framer, protocol version
    BridgeProcess.swift   child process + framing (actor, timeouts, bye)
    AgentBridge.swift     app-facing state machine: state / agentState /
                          status (character identity) / isBusy / requests
  MenuCard/             tray dropdown card + settings HUD (+ store)
  ChatWindow/           native chat: controller · view · transcript rows
                        · view-model (send pipeline, event chips)
  Avatar/               VoiceOrbView (TimelineView+Canvas spectrum ring)
                        + orb-only and orb+chat window controllers
  Floating/             pill quick-input: panel · view · hotkey · bridge
  Voice/                VoiceRecorder + TTS/ (manager, Apple synth)
                        + STT/ (manager, Apple, Whisper)
  Intents/              App Intents seam (Siri/Shortcuts): AskJaeger,
                        EveningRoutine — both via AgentBridge, isolated
                        sessions ("siri" / "routine")
  Splash/               boot progress window
  Theme/                Term — the terminal palette every dark surface uses
  Resources/            menu-bar icons, splash hero
```

Conventions:

* **State down, actions up.** Views read `AgentBridge.shared` /
  `TTSManager.shared` publishers; side-effects live in view-models or
  controllers, never in view bodies.
* **Identity is `status`.** The active character (name + icon) rides
  `AgentBridge.status`; every surface (tray card, chat title/status bar,
  orb face) re-brands from that one publisher. A `select_character`
  command refreshes it automatically (`refreshIdentity()`).
* **Windows are lazy singletons** — created on first open, reused after,
  closing never quits (quit lives in the tray card and tears the core
  down through `bye`).
* Keep files under ~400 lines; split view files by layout vs. typography
  (see `ChatView` / `ChatTranscript`).

## The seam (frozen v1)

```
app → bridge:  {"op":"send"|"respond"|"quit"|"query"|"command", ...}
bridge → app:  ready · agent_state · state · tool · reply · result ·
               request · fatal · bye
```

Fast-ready: `ready` lands before the model loads (queries/settings work
immediately); `agent_state` streams booting → ready/failed. New read-only
`query` whats are additive and allowed; frame shapes are frozen — change
`protocol.py` + fixtures + both test suites together or not at all.

## Known follow-ups

* Speaking-state orb amplitude is a proxy waveform (Apple TTS exposes no
  amplitude tap) — real amplitude/audio frames over the bridge is the
  noted follow-up, matching the PySide6 orb's proxy fallback.
* Mic toggle persists `voice.enabled` (applies on restart); a live
  voice-input loop lands with the STT wiring.
* Code-signing/notarization for distribution builds.
