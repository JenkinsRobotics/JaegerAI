# WebUI-embedded chat shell — spike result (card_b1a5afefda)

> **Historical spike.** Jaeger WebUI is now first-party source under
> `jaeger_ai/features/webui`; the old submodule path below no longer exists.

Date: 2026-09-14 · Author: Assistant (JROS idle tick) · Status: spike complete, acceptance run pending

## What shipped

1. `jaeger_ai/interfaces/swift/Sources/JaegerAI/ChatWindow/ChatSurfaceFeatureFlags.swift`
   — `ChatSurfaceFeatureFlags.useWebUITranscript`, true iff env
   `JAEGER_CHAT_SURFACE=webui`. Default OFF: the app is byte-for-byte
   unchanged without the env var.
2. `ChatView.swift` chat-tab branch now reads the flag first and renders
   `WebUIChatContainer()` (the previously orphaned WKWebView surface in
   `WebUIChatSurface.swift`) when set; the native empty-state/`messageList`
   branch is untouched otherwise.
3. `swift build` passes (9.0s, zero warnings in the touched files).

## What already existed (found, not built)

- `WebUIChatSurface.swift` — full WKWebView host: profile-cookie pinning
  (`hermes_profile=jaeger`, mandatory — the hermes profile lists 0
  sessions), endpoint resolution via `WebUIEndpoint` (`jaeger webui url`,
  15s timeout, falls back to `http://127.0.0.1:8790/`), JS prompt
  injection into the composer, new-chat injection, loading/error states
  with Retry + Open-in-Safari. It was dead code — nothing referenced it.
- `WebUIEndpoint.resolve()` — already used by App Intents, Settings HUD,
  ServerControls, and ChatView's "open in browser" action.

## Live verification (2026-09-14, this tick)

| Check | Result |
| --- | --- |
| `jaeger webui url` | `http://127.0.0.1:8790/` (Tailscale URL when run off-Mac) |
| GET / title | `Jaeger` |
| HTML `__HERMES_WEBUI_BUNDLE_VERSION__` | `exp-v0.52.264-15-g0c79c12b` |
| `/api/settings` `webui_version` | `exp-v0.52.264-15-g0c79c12b` — MATCH, no skew banner |
| `GET :8791/health` | `ok: true`, instance `jaeger`, proto 1, streaming capable |

## How to A/B the two renderers

```
cd ~/GitHub/JaegerAI/jaeger_ai/interfaces/swift
JAEGER_CHAT_SURFACE=webui .build/debug/JaegerAI      # WebUI in WKWebView
.build/debug/JaegerAI                                # native transcript (default)
```

## Acceptance checklist (needs a human at the window — next session)

- [ ] Embedded window shows composer + "Worked for…" chip on a live turn
      (chat_activity_display_mode=transparent_stream)
- [ ] Streaming renders token-by-token in the embedded view
- [ ] Session continuity: reload keeps the session; a second device/browser
      on the same `hermes_profile=jaeger` profile sees the same session
- [ ] Identity stays green across a WebUI redeploy (no version-skew banner)
- [ ] Voice/orb/App Intents still work with the bridge as control plane

## Design note: dropping the :8790 hard dependency (Electron model)

Today the surface loads `WebUIEndpoint.resolve()` — a live HTTP origin on
:8790 served by `com.jenkinsrobotics.jaeger-webui`. To package the WebUI
dist in the app bundle later:

1. Copy `vendor/hermes-webui` dist into the SwiftPM `Resources/webui/`
   (`.copy` resource rule; keep the `__WEBUI_VERSION__` stamp step in the
   build script so identity still matches `/api/settings`).
2. Register a custom `WKURLSchemeHandler` (`jaeger-local://`) in
   `WKWebViewConfiguration.setURLSchemeHandler(_:forURLScheme:)` that
   serves those files with correct MIME types.
3. Keep ALL API/streaming traffic pointed at the adapter origin (:8791,
   Tailscale or loopback) — the renderer is static; the engine stays
   remote. This is exactly the Electron model (local shell, remote
   engine) and removes the "app opens empty when :8790 is down" failure
   mode while keeping one renderer and one wire protocol.
4. The profile cookie must be set for the custom scheme's host too
   (`WKHTTPCookieStore` accepts it; `WebUIChatController.profileCookie`
   already keys off `url.host`).

## Non-goals (unchanged)

- The jaeger bridge keeps every control-plane duty (open window, voice,
  orb, App Intents, session listing). ChatTranscript /
  ThoughtDisclosureView / ToolCommandGroupView stay in the tree behind
  the default-off flag — demoted, not deleted.

## Known issues found during the spike (2026-09-14, end of tick)

- AmbientLoopTests hangs the entire `swift test` suite: an AVAudioEngine
  thread (AUScheduledParameterRefresher) never yields — verified by
  `sample` on a stuck xctest process. Pre-existing, unrelated to this
  change. Run `swift test --skip AmbientLoopTests` until fixed.
- Xcode license agreement went pending mid-session: `swift --version`
  now refuses with "not agreed to the Xcode license agreements".
  Operator must run `sudo xcodebuild -license` before any further
  swift build/test. The 9.0s green build above predates this.
- JROS instance venv python is dyld-broken (libpython3.12.dylib missing
  from venv/lib) — crashes start_background/run_in_venv at startup.
  Workaround: sanitized PATH + nohup-detached jobs.
