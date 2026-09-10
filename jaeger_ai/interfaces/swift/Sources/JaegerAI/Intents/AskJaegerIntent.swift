//
//  AskJaegerIntent.swift
//  JaegerAI / Intents
//
//  App Intents seam so Siri and Shortcuts can drive the JaegerAI macOS app
//  (iOS 26-style App Intents on macOS 14+; App Intents are cross-platform).
//
//  Design contract (matches the repo's Bridge seam):
//    * Everything goes through AgentBridge (BridgeProcess child).
//    * Sessions are isolated on the Python side (sessions.db) — Siri gets
//      "siri", routines get "routine", desktop chat keeps "desktop-app".
//    * No polling loops: intents await the existing sendChat round-trip.
//

import AppIntents

// MARK: - Shared plumbing

/// One place that owns "make sure the bridge is up, then send a turn."
/// App Intents run in-process here (no extension), so the shared
/// ``AgentBridge`` singleton is valid to use directly.
@MainActor
enum JaegerIntentSupport {
    /// Ensure transport is connected (spawns the `jaeger bridge` child if
    /// the app is foregrounded from the background for an intent run).
    static func ensureConnected() async throws {
        if AgentBridge.shared.state != .ready {
            try await AgentBridge.shared.connect()
        }
    }

    /// Send one turn and return the reply text. Throws on transport failure;
    /// stalls come back as text (matching sendChat's recovery semantics).
    static func send(_ text: String, session: String) async throws -> String {
        try await ensureConnected()
        let result = try await AgentBridge.shared.sendChat(text: text, session: session)
        return result.text
    }
}

// MARK: - AskJaegerIntent

/// "Hey Siri, ask Jaeger …" — freeform question, answer spoken/shown.
/// Uses Apple's newer `.prompt` pattern so Siri collects the query with
/// its own UI, then we hand it to the agent.
struct AskJaegerIntent: AppIntent {
    static let title: LocalizedStringResource = "Ask Jaeger"
    static let description = IntentDescription(
        """
        Ask JaegerAI a question. The reply comes back from your local \
        Jaeger agent over the bridge.
        """,
        category: .information
    )

    /// Optional prompt — when omitted, Siri prompts the user live.
    @Parameter(title: "Question", requestValueDialog: IntentDialog("What should I ask Jaeger?"))
    var question: String?

    static var openAppWhenRun: Bool { false }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let asked = question?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !asked.isEmpty else {
            return .result(dialog: "I didn't catch a question.")
        }
        do {
            let reply = try await JaegerIntentSupport.send(asked, session: "siri")
            return .result(dialog: IntentDialog(stringLiteral: reply))
        } catch {
            return .result(dialog: "Jaeger bridge error: \(error.localizedDescription)")
        }
    }
}

// MARK: - JaegerShortcuts (phrase registration)

/// Registers the two intents as Siri phrases and exposes them in
/// Shortcuts / Spotlight / Action Button. Namespaces keep the app
/// identifier unique on-device.
struct JaegerShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: AskJaegerIntent(),
            phrases: [
                "Ask \(.applicationName)",
            ],
            shortTitle: "Ask Jaeger",
            systemImageName: "brain.head.profile"
        )
        AppShortcut(
            intent: EveningRoutineIntent(),
            phrases: [
                "Run \(.applicationName) evening routine",
                "\(.applicationName) wind down",
            ],
            shortTitle: "Evening Routine",
            systemImageName: "moon.stars"
        )
    }
}