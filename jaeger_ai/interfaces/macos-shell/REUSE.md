# Reuse log — jaeger_ai/interfaces/macos-shell

Standing rule: this is a refactor, not a rebuild. Working logic from Jaeger's own
`jaeger_ai/interfaces/swift` (Jenkins Robotics, same repo) is **copied** here when it is better or more
complete and does not depend on the old NDJSON bridge (`AgentBridge`/`BridgeProcess`), `ChatViewModel`,
`SettingsStore` or the old SwiftUI app. The old target is never imported or linked, and its files are unchanged.
Paths below are relative to `jaeger_ai/interfaces/swift/Sources/JaegerAI/` (old) and this package (new).

| Old file:lines | New file | Status | Reason |
|---|---|---|---|
| `Floating/PillHotkey.swift:30-165` | `Sources/JaegerShell/Hotkey.swift` | adapted (S2) | Carbon `RegisterEventHotKey`, no Accessibility permission. Configurable spec (`JaegerHotkey`), returns status, main-queue dispatch. |
| `JaegerAIApp.swift:116-150` (running/off icon pair) | `Sources/JaegerShell/StatusItemController.swift` | adapted | Same `jaeger_icon_22` / `jaeger_icon_off_22` PNGs at 18×18; off icon when the WebUI probe fails. |
| `JaegerAIApp.swift:47-110` (`MenuBarExtra` scene) | — | not reused | SwiftUI `App` scene tied to the old app; the shell is an AppKit `NSStatusItem` app. |
| `JaegerMechIcon.swift` | — | not reused | SwiftUI `Shape`; the shell uses the PNG icons (as the old status item did). |
| `Bridge/StackManager.swift:13-47` (reply types) | `Sources/JaegerShellCore/StackCLI.swift` | ported | Public + Equatable, `summary()` added, unit-tested. |
| `Bridge/StackManager.swift:75-101` (`runStackCommand`) | `Sources/JaegerShell/StackRunner.swift` | adapted | Callback instead of `Task.detached`; stderr read concurrently; same 120 s watchdog. Used only by the confirm-gated Start. |
| `Bridge/StackManager.swift:53-73` (`up/down/reset/status`) | `StatusItemController.runStackUp` | adapted (up only) | Only `stack up --json` behind the confirm sheet (Q4). `down`/`reset` not reused; `status` arguments kept in `StackCLI` for later. |
| `Bridge/StackManager.swift:106-180` (`LifecycleLeaseBeat`) | — | not reused | Lease for the old app's automatic stack lifecycle; the shell never owns the stack lifecycle. |
| `Bridge/ProcessTree.swift` | — | not reused | Process-tree teardown for stack down/quit; not used by the shell. |
| `MenuCard/ServerControls.swift` | — | not reused | SwiftUI controls coupled to `BridgeProcess`. |
| `Bridge/BridgeProcess.swift:215-239` (`jaegerPath()`) | `Sources/JaegerShellCore/Launcher.swift` | adapted | Same order (`JAEGER_VENV`, `JaegerLauncher`, walk up from the bundle, `JAEGER_REPO`/`~/GitHub/JaegerAI`). `JAEGER_BRIDGE_CMD` dropped; every candidate must be executable; extra fallbacks. Unit-tested. |
| `MenuCard/LaunchAtLogin.swift:45-62` | `ShellEnvironment.setLoginItem` (`JaegerShellApplication.swift`) | adapted | Guarded register/unregister + status. Used by the menu and the bridge. |
| `MenuCard/LaunchAtLogin.swift:24-35` (default registration) | — | **not ported (bug)** | Registered Launch at Login on every fresh install. The shell is opt-in only. |
| `Bridge/GatewayClient.swift:5-45` (Keychain caller token via `security`) | — | not reused | The shell makes no authenticated gateway calls (only `GET /health`), so it never reads the token. |
| notifications | `NativeBridge.bridgeNotify` | new | The old app had no notification code; `UNUserNotificationCenter` is new. |
| `Voice/STT/STTBackend.swift:29-90` | `Sources/JaegerShell/Voice/STTBackend.swift` | ported (S4) | Protocol, result and error types. |
| `Voice/STT/AppleSpeechSTT.swift:34-215` | `Sources/JaegerShell/Voice/AppleSpeechSTT.swift` | adapted (S4) | On-device recognition required only when the recognizer supports it; shell log tags. |
| `Voice/STT/STTManager.swift:16-58` | — | not reused | Only chose between the Whisper stub and Apple Speech; the shell calls Apple Speech directly. |
| `Voice/STT/WhisperSTT.swift:43-90` | — | not reused | Stub; no model is bundled. |
| `Voice/VoiceRecorder.swift:57-80, 167-279, 283-339` | `Sources/JaegerShell/Voice/VoiceRecorder.swift` (+ `JaegerShellCore/AudioMath.swift`) | adapted (S4) | Mic permission, AVAudioEngine tap, capture buffer. No ObservableObject, monitoring or barge-in; mono mix-down + RMS moved to Core (unit-tested). |
| `Voice/SpeechEnergyDetector.swift`, `Voice/AmbientLoop.swift`, `Voice/AmbientCoordinator.swift` | — | not reused (deferred) | Barge-in/ambient loop; the ambient pieces depend on `GatewayClient`. |
| `Voice/TTS/TTSBackend.swift:64-155` (`TTSError`, `TTSText`) | `Sources/JaegerShellCore/TTSText.swift` | ported (S4) | Markdown→speech text; unit-tested. |
| `Voice/TTS/AppleSpeechSynth.swift:32-196` | `Sources/JaegerShell/Voice/AppleSpeechSynth.swift` | adapted (S4) | No VoiceStage; voice choice via `VoiceCatalog`; silent `render()` (AVSpeechSynthesizer.write) for headless checks. |
| `Voice/TTS/VoiceStage.swift:57-75, 114-127, 149-152` | `Sources/JaegerShellCore/VoiceCatalog.swift` | adapted (S4) | Persona voice tables + first-installed resolver, pure and unit-tested. Installer stage not reused. |
| `Voice/TTS/TTSManager.swift:20-219` | — | not reused | Kokoro path goes through `AgentBridge` `speak`, and the class is coupled to `ChatViewModel`. Kokoro stays available web-side (WebUI TTS route). |
| `jaeger_ai/interfaces/swift/Resources/Info.plist:35-40` (usage strings) | `Resources/Info.plist` | adapted (S4) | Mic + speech recognition descriptions reworded for the shell. Camera/AppleEvents not needed. |
| rest of repo | — | not reused | No other Swift code; the PySide6 and web voice paths are Python/JS, not portable to the Swift shell. |
