# Swift UI — Parity Plan (corrected 2026-07-01)

Goal: the native **Swift/SwiftUI** app at **full parity** with the shipping PySide6
surfaces. It is now the **default** windowed UI (`interaction.ui = "swift"`).

## 1. Current state — MUCH further along than a skeleton

`interfaces/swift/` is a 23-file SwiftPM app that **builds clean** (`swift build -c
release` → `JaegerOS`). Already implemented:

- **Connection:** `Bridge/BridgeProcess.swift` + `AgentBridge.swift` — spawns
  `jaeger bridge` (Python NDJSON stdio child, `interfaces/bridge.py`) and exchanges
  newline-JSON. Same agent the PySide6 app runs, one hop out. No socket/gateway.
- **Chat:** `ChatView` / `ChatViewModel` / `ChatWindowController`.
- **Pill:** `PillView` / `PillPanel` / `PillHotkey` (⌥Space) / `PillBridge`.
- **Tray:** `MenuCard` (menu-bar card).
- **Settings:** `SettingsView`.
- **Voice:** `TTSManager` — speech routes to the agent's Kokoro voice over the
  bridge `speak` command (config `voice.speech_engine`, default `kokoro`; active
  character's voice_id), with `AppleSpeechSynth` as the `apple` engine and the
  automatic fallback when the bridge is down; `STTManager` + `AppleSpeechSTT` +
  `WhisperSTT`; `VoiceRecorder`. HUD picker for the engine: follow-up (settings
  HUD is in flight).
- Separate `interfaces/avatar/` — Metal + `URLSessionWebSocketTask` avatar renderer.

## 2. The seam (actual, not the WS gateway I wrongly proposed)

`jaeger bridge` NDJSON over stdin/stdout:
```
bridge → app:  {"type":"ready","instance","model"} | {"type":"state","busy"}
               | {"type":"reply","text","error"} | {"type":"fatal","error"}
app → bridge:  {"text": <turn>} | {"op":"quit"}
```
This does **chat + busy-state only**. Richer surfaces need more data — two routes:
- **Extend `bridge.py`** to emit more frames (agent_state phases, tts amplitude for
  the orb, and query/command for character/config/permissions), OR
- **Read files directly** in Swift (character/config/permissions are on-disk on the
  same Mac — same as the PySide6 settings HUD does).
Recommendation: files-direct for settings/library/permissions; extend the bridge for
live orb data (tts amplitude / audio frames / agent-state phases).

## 3. launch integration — DONE

- `InteractionConfig.ui: "pyside6" | "swift" = "swift"`.
- `launch.py cmd_boot_windowed` → `_ui_toolkit()` reads config; `_boot_swift()` does
  `swift build -c release` + runs `JaegerOS` with the venv on PATH; **falls back to
  PySide6** on any failure.
- App Settings → "Windowed UI toolkit" selector.

## 4. Parity gaps vs the current PySide6 UI (the real remaining work)

1. **Avatar voice orb** — face + radial spectrum; thinking wave; speaking FFT
   (Accelerate/vDSP) from bridge-supplied tts amplitude / audio frames, proxy
   fallback. Fold in `interfaces/avatar/` (already Metal+WS) or a SwiftUI `Canvas`.
2. **Agent-settings HUD** — rebuild `SettingsView` as the character-centric HUD:
   left rail (Home·Library·Character·Traits·App·Permissions), agent panel, Library
   card grid (Select / Make Default), trait sliders, permission grants, all
   setpoints incl. mic/speaker + UI toolkit. Needs character/config/permissions
   read+write (files-direct) + select/make-default.
3. **Tray parity** — bring `MenuCard` to the new tray: character avatar+name+status,
   action bar (chat·agent·quick-input), settings + power. Caret + click-away.
4. **Avatar+chat window** — orb + chat split + mic/speaker toggles.
5. **Character system** — active character drives name/icon everywhere (bridge should
   report the active character; or Swift reads active_character).

## 5. Phases (revised — most of 1–2 already exist)

- **P1 — launch + connection** ✅ (this session).
- **P2 — bridge data extension**: add agent-state phases + tts amplitude (+ optional
  audio frames) to `bridge.py`; Swift consumes them. Unblocks the orb.
- **P3 — avatar orb** in the chat/companion window.
- **P4 — settings HUD** (files-direct read/write) to full parity.
- **P5 — tray restructure** to match; polish; then confirm parity & keep Swift default.

## 6. Notes / risks

- Swift is a separate build (SwiftPM) + eventual code-signing/notarization.
- Extending `bridge.py` is additive (a surface), not a broker/topology change — but
  confirm scope before adding command/query verbs.
- Parity is measured against the frozen PySide6 set; new PySide6 surfaces get added
  to §4 before Swift can claim parity.
