//
//  StackStatusIntent.swift
//  JaegerAI / Intents
//
//  Reports live fabric status via `jaeger status` (read-only; does not start services).
//

import AppIntents
import Foundation

struct StackStatusIntent: AppIntent {
    static let title: LocalizedStringResource = "Jaeger Stack Status"
    static let description = IntentDescription(
        "Show the live Jaeger multi-agent fabric status (`jaeger status`)."
    )

    static var openAppWhenRun: Bool { false }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        do {
            let out = try await JaegerIntentSupport.runJaegerCLI(["status"])
            let trimmed = out.trimmingCharacters(in: .whitespacesAndNewlines)
            let dialog = trimmed.isEmpty
                ? "jaeger status returned no output. WebUI default: \(JaegerIntentConstants.webUIURLString)"
                : String(trimmed.prefix(1500))
            return .result(dialog: IntentDialog(stringLiteral: dialog))
        } catch {
            return .result(
                dialog: IntentDialog(
                    stringLiteral: "Status check failed: \(error.localizedDescription). WebUI: \(JaegerIntentConstants.webUIURLString)"
                )
            )
        }
    }
}
