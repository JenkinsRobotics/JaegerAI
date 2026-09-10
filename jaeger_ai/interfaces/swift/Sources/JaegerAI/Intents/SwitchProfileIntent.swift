//
//  SwitchProfileIntent.swift
//  JaegerAI / Intents
//
//  Switch the active Hermes WebUI profile via POST /api/profile/switch on
//  canonical chat (:8790). Does not start the stack; fails closed when cold.
//

import AppIntents
import Foundation

struct SwitchProfileIntent: AppIntent {
    static let title: LocalizedStringResource = "Switch Jaeger Profile"
    static let description = IntentDescription(
        "Switch the active Jaeger WebUI profile (default / jaeger / openclaw / roundtable) via HTTP :8790."
    )

    @Parameter(title: "Profile", requestValueDialog: IntentDialog("Which profile should Jaeger use?"))
    var profile: String

    static var openAppWhenRun: Bool { false }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let raw = profile.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty else {
            return .result(dialog: "No profile name given.")
        }
        let name = JaegerIntentSupport.normalizeProfileName(raw)

        do {
            // Best-effort validate against live catalog when WebUI is up.
            if let catalog = try? await JaegerIntentSupport.webUIJSON(method: "GET", path: "/api/profiles") {
                if let profiles = catalog.json["profiles"] as? [[String: Any]] {
                    let known = Set(profiles.compactMap { ($0["name"] as? String)?.lowercased() })
                    // Root/default often listed as "default"; aliases already normalized.
                    if !known.isEmpty && !known.contains(name.lowercased()) && name != "default" {
                        let listed = known.sorted().joined(separator: ", ")
                        return .result(dialog: "Unknown profile \"\(name)\". Known: \(listed)")
                    }
                }
            }

            let (_, json, _) = try await JaegerIntentSupport.webUIJSON(
                method: "POST",
                path: "/api/profile/switch",
                body: ["name": name]
            )
            let active = (json["name"] as? String)
                ?? (json["active"] as? String)
                ?? (json["profile"] as? String)
                ?? name
            let pathHint = (json["path"] as? String).map { " (\($0))" } ?? ""
            return .result(
                dialog: IntentDialog(stringLiteral: "Switched Jaeger profile to \(active)\(pathHint).")
            )
        } catch {
            return .result(
                dialog: IntentDialog(
                    stringLiteral: "Could not switch profile to \"\(name)\": \(error.localizedDescription)"
                )
            )
        }
    }
}
