//
//  EveningRoutineIntent.swift
//  JaegerAI / Intents
//
//  Midnight-trigger companion: an App Intent that fires a deterministic
//  wind-down prompt at the agent and returns its reply. Built to be the
//  action of a Shortcuts **Personal Automation** (Shortcuts app →
//  Automation → Time of Day → 12:00 AM → Run: "Jaeger Evening Routine").
//
//  (iOS 26-style App Intents on macOS 14+; App Intents are cross-platform).
//

import AppIntents

/// The midnight intent itself. Session-isolated ("routine") so routine
/// traffic never mixes with desktop chat or Siri Q&A history.
struct EveningRoutineIntent: AppIntent {
    static let title: LocalizedStringResource = "Jaeger Evening Routine"
    static let description = IntentDescription(
        "Ask JaegerAI to run the evening wind-down: summarize today, list unfinished work for tomorrow, and log the routine run."
    )

    /// Optional note; automation can leave it empty.
    @Parameter(title: "Day note", default: "")
    var dayNote: String

    static var openAppWhenRun: Bool { false }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let note = dayNote.trimmingCharacters(in: .whitespacesAndNewlines)
        let prompt = """
        Evening routine check-in. It's midnight. \
        \(note.isEmpty ? "No extra note today." : "Notes from today: \(note).") \
        Do the wind-down: summarize the day, list anything unfinished for tomorrow, \
        and confirm the journal entry is recorded.
        """
        do {
            let reply = try await JaegerIntentSupport.send(prompt, session: "routine")
            return .result(dialog: IntentDialog(stringLiteral: reply))
        } catch {
            return .result(dialog: "Evening routine failed: \(error.localizedDescription)")
        }
    }
}
