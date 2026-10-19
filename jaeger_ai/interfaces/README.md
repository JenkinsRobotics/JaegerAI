# Interfaces

The canonical Mac app is `macos-shell/` hosting the shared `ui/` frontend. `ide/`, `tui/`, `avatar/`, bridge, MCP and other peer transports remain supported independent surfaces. Required WebUI proxy/backend lives under `features/webui`.

Old SwiftUI and Qt desktop/chat/avatar frontends are preserved only in the Desktop legacy archive. There are no automatic fallbacks to those apps. `native_multimodal/` contains only the extracted bridge adapter and device diagnostics; camera/ambient UI integration is currently unavailable in the shell. See `docs/integration/SCOPED_CLEANUP.md` for capabilities and migration blockers.
