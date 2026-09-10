//
//  RunRoutineIntent.swift
//  JaegerAI / Intents
//
//  Generic routine runner — sends a named routine prompt over the bridge
//  (session "routine"), sibling to EveningRoutineIntent.
//

import AppIntents

struct RunRoutineIntent: AppIntent {
    static let title: LocalizedStringResource = "Run Jaeger Routine"
    static let description = IntentDescription(
        "Run a named Jaeger routine by sending a prompt to the local agent over the bridge."
    )

    @Parameter(title: "Routine", requestValueDialog: IntentDialog("Which routine should I run?"))
    var routine: String

    @Parameter(title: "Notes", default: "")
    var notes: String

    static var openAppWhenRun: Bool { false }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let name = routine.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else {
            return .result(dialog: "No routine name given.")
        }
        let note = notes.trimmingCharacters(in: .whitespacesAndNewlines)
        let prompt = """
        Run the "\(name)" routine now. \
        \(note.isEmpty ? "No extra notes." : "Notes: \(note).") \
        Follow the routine playbook if one exists; otherwise outline the steps and execute what you can locally.
        """
        do {
            let reply = try await JaegerIntentSupport.send(prompt, session: "routine")
            return .result(dialog: IntentDialog(stringLiteral: reply))
        } catch {
            return .result(dialog: "Routine \"\(name)\" failed: \(error.localizedDescription)")
        }
    }
}
