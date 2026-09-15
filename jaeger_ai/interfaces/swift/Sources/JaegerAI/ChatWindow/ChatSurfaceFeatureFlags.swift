//
//  ChatSurfaceFeatureFlags.swift
//  JaegerAI / ChatWindow
//
//  Spike gate for kanban card_b1a5afefda — "one chat renderer, two shells".
//
//  Rationale (verified 2026-09-14): ChatGPT/Claude desktop, Cursor, and
//  Claude Code all embed ONE web renderer in a native shell. Jaeger
//  currently maintains two renderers (WebUI HTML/JS on :8790 + Swift
//  ChatTranscript) on two wire protocols (adapter :8791 streaming vs
//  bridge NDJSON), which already caused feed drift (compact worklog vs
//  Thought process / Ran N commands).
//
//  This flag DEMOTES (does not delete) the native transcript: with the
//  env var unset the app behaves exactly as before; setting
//  JAEGER_CHAT_SURFACE=webui swaps the chat tab's transcript for the
//  WebUI hosted in WKWebView (WebUIChatSurface.swift). The jaeger bridge
//  stays the control plane either way (open window, voice, orb, App
//  Intents, session listing).
//
//  Env-var (not UserDefaults) so a single launch line
//  `JAEGER_CHAT_SURFACE=webui .build/debug/JaegerAI` A/B-tests the two
//  renderers side by side without touching persisted state.
//

import Foundation

enum ChatSurfaceFeatureFlags {
    /// When true, the chat tab renders the Jaeger WebUI (vendor/hermes-webui
    /// on :8790, resolved via `jaeger webui url`) inside WKWebView instead
    /// of the native ChatTranscript. Default: native renderer.
    static var useWebUITranscript: Bool {
        ProcessInfo.processInfo.environment["JAEGER_CHAT_SURFACE"] == "webui"
    }
}
