# menubar-shell

Job: Jaeger in the Mac menu bar. A thin control shell, not a second brain, and not a second app.

This module does NOT copy the Mac app code. The code already lives in this repo, at jaeger_ai/interfaces/macos-shell/, and copying it here would create a second, drifting copy. This folder is the stack registration for that interface: what it is, how it runs, how it bolts on, and what to test.

Source in this repo (current, verified 2026-10-22):
- jaeger_ai/interfaces/macos-shell/Package.swift
- jaeger_ai/interfaces/macos-shell/Sources/JaegerShell/ — JaegerShellApplication.swift (31,161 bytes), Snapshot, VisibleCheck, VerifyBridge, NativeBridge, StackController, NativeChrome, StatusItemController.swift (menu bar status item), LeaseBeat, Hotkey.swift, StackRunner, Aether/, Voice/
- jaeger_ai/interfaces/macos-shell/Sources/JaegerShellCore/, Tests/, Jaeger Dev.app, REUSE.md, ATTRIBUTION.md

What it does: menu bar status item, hotkey, stack Start/Stop (confirm-gated), lifecycle lease, voice (STT/TTS), and it loads the new UI through the WebUI backend on :8790, with Gateway health on :33418. It is a shell/control app: it does not own sessions, memory, or execution.

How it bolts on:
- This is a refactor, not a rebuild, of the old jaeger_ai/interfaces/swift menubar app (now in Desktop/Jaeger-UI-Archive-2026-10-17/macos-menubar-app/). See interfaces/macos-shell/REUSE.md for exactly what was copied/adapted and what was intentionally NOT reused (old NDJSON bridge, ChatViewModel, SettingsStore, old SwiftUI app scene, GatewayClient Keychain token, barge-in/ambient loop deferred).
- Build/run from the macos-shell Swift package, not from the archive. The archive app is never imported or linked.
- It talks to the same Gateway as the IDE client and the WebUI, with the same identity and the same approval gate.

Do NOT add a second Mac app from the Desktop archives (old Swift menubar app wholesale, python-desktop-ui legacy PySide6, Legacy-Archive SwiftUI snapshots). One menu bar shell only.

Test to run when code-run is available: build the shell, check the menu bar status item appears and reflects Gateway health (running/off icon), check Start/Stop are confirm-gated, check hotkey works without Accessibility permission (per REUSE.md), check the UI loads via WebUI :8790, check voice STT/TTS, check quitting retires the lifecycle lease correctly.
