//
//  FinanceIntent.swift
//  JaegerAI / Intents
//
//  Native App Intents for Siri and Shortcuts to query finances and budgets.
//

import AppIntents
import Foundation

// MARK: - CheckFinancesIntent

struct CheckFinancesIntent: AppIntent {
    static let title: LocalizedStringResource = "Check Finances"
    static let description = IntentDescription("Ask JaegerAI to report your live net worth, cash flow, and account balances via Monarch Money.")

    static var openAppWhenRun: Bool { false }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        do {
            let reply = try await JaegerIntentSupport.send(
                "Check my current net worth, financial account balances, and recent cash flow via Monarch Money.",
                session: "finance"
            )
            return .result(dialog: IntentDialog(stringLiteral: reply))
        } catch {
            return .result(dialog: "Unable to check finances: \(error.localizedDescription)")
        }
    }
}

// MARK: - CheckBudgetIntent

struct CheckBudgetIntent: AppIntent {
    static let title: LocalizedStringResource = "Check Budget"
    static let description = IntentDescription("Ask JaegerAI to check your monthly budget categories and spending pace via Monarch Money.")

    @Parameter(title: "Category", description: "Optional category to check (e.g. Dining, Groceries)")
    var category: String?

    static var openAppWhenRun: Bool { false }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let prompt: String
        if let cat = category?.trimmingCharacters(in: .whitespacesAndNewlines), !cat.isEmpty {
            prompt = "How much have I spent on \(cat) this month and what is my remaining budget in Monarch Money?"
        } else {
            prompt = "Review my overall budget performance and category pacing this month in Monarch Money."
        }
        do {
            let reply = try await JaegerIntentSupport.send(prompt, session: "finance")
            return .result(dialog: IntentDialog(stringLiteral: reply))
        } catch {
            return .result(dialog: "Unable to check budget: \(error.localizedDescription)")
        }
    }
}
