//
//  OpenChatIntent.swift
//  JaegerAI / Intents
//
//  Opens the Jaeger WebUI chat in the default browser.
//  Uses the canonical loopback URL (http://127.0.0.1:8790/) as a constant;
//  optionally prefers `jaeger webui url` when the CLI resolves cleanly.
//

import AppIntents
import AppKit
import Foundation

struct OpenChatIntent: AppIntent {
    static let title: LocalizedStringResource = "Open Jaeger Chat"
    static let description = IntentDescription(
        "Open the Jaeger WebUI chat in your browser (default http://127.0.0.1:8790/)."
    )

    static var openAppWhenRun: Bool { false }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        var url = JaegerIntentConstants.webUIURL
        // Best-effort CLI discovery — never starts the stack; falls back to :8790.
        if let resolved = try? await WebUIEndpoint.resolve() {
            url = resolved
        }
        let ok = NSWorkspace.shared.open(url)
        if ok {
            return .result(dialog: IntentDialog(stringLiteral: "Opened \(url.absoluteString)"))
        }
        return .result(dialog: "Could not open \(url.absoluteString)")
    }
}
