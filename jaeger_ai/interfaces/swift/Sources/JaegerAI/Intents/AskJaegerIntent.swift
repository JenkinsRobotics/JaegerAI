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
import Foundation

// MARK: - Shared plumbing

/// Canonical WebUI loopback URL while discovery/`jaeger webui url` is optional.
enum JaegerIntentConstants {
    static let webUIURLString = "http://127.0.0.1:8790/"
    static let webUIURL = URL(string: webUIURLString)!
}

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

    /// Run `jaeger <args…>` and capture stdout (best-effort; does not start the stack).
    static func runJaegerCLI(_ arguments: [String], timeoutSeconds: Double = 20) async throws -> String {
        try await Task.detached {
            let process = Process()
            let output = Pipe()
            let err = Pipe()
            process.executableURL = URL(fileURLWithPath: BridgeProcess.jaegerPath())
            process.arguments = arguments
            process.standardOutput = output
            process.standardError = err
            try process.run()
            let timeout = Task {
                try? await Task.sleep(for: .seconds(timeoutSeconds))
                if !Task.isCancelled && process.isRunning { process.terminate() }
            }
            defer { timeout.cancel() }
            let data = output.fileHandleForReading.readDataToEndOfFile()
            let errData = err.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            let stdout = String(data: data, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            let stderr = String(data: errData, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if process.terminationStatus != 0 {
                let detail = stderr.isEmpty ? stdout : stderr
                throw BridgeError.launchFailed(
                    "jaeger \(arguments.joined(separator: " ")) failed (\(process.terminationStatus)): \(detail)"
                )
            }
            return stdout.isEmpty ? stderr : stdout
        }.value
    }

    /// Resolve WebUI base URL without starting services.
    static func resolveWebUIBase() async -> URL {
        if let resolved = try? await WebUIEndpoint.resolve() {
            return resolved
        }
        return JaegerIntentConstants.webUIURL
    }

    /// Normalize spoken / Shortcuts profile aliases to Hermes profile ids.
    static func normalizeProfileName(_ raw: String) -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        let key = trimmed.lowercased()
        switch key {
        case "hermes", "hermes agent", "default", "agent":
            return "default"
        case "jaeger", "jaegerai", "jaeger ai":
            return "jaeger"
        case "openclaw", "open claw", "claw":
            return "openclaw"
        case "roundtable", "round table", "rt":
            return "roundtable"
        default:
            return trimmed
        }
    }

    /// POST JSON to WebUI. Does not start the stack; throws on connect failure.
    static func webUIJSON(
        method: String,
        path: String,
        body: [String: Any]? = nil,
        timeoutSeconds: TimeInterval = 12
    ) async throws -> (status: Int, json: [String: Any], setCookie: String?) {
        let base = await resolveWebUIBase()
        guard var components = URLComponents(url: base, resolvingAgainstBaseURL: false) else {
            throw BridgeError.launchFailed("Bad WebUI URL: \(base.absoluteString)")
        }
        // Keep scheme/host/port from resolve; replace path.
        let trimmedPath = path.hasPrefix("/") ? path : "/\(path)"
        components.path = trimmedPath
        components.query = nil
        guard let url = components.url else {
            throw BridgeError.launchFailed("Could not build WebUI URL for \(path)")
        }

        var request = URLRequest(url: url, timeoutInterval: timeoutSeconds)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body, options: [])
        }

        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch {
            throw BridgeError.launchFailed(
                "WebUI unreachable at \(url.absoluteString) (stack may be stopped). \(error.localizedDescription)"
            )
        }
        guard let http = response as? HTTPURLResponse else {
            throw BridgeError.launchFailed("Non-HTTP response from WebUI")
        }
        let setCookie = http.value(forHTTPHeaderField: "Set-Cookie")
        let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        if !(200..<300).contains(http.statusCode) {
            let detail = (obj["error"] as? String)
                ?? (obj["detail"] as? String)
                ?? String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
                ?? "HTTP \(http.statusCode)"
            throw BridgeError.launchFailed("WebUI \(method) \(path) → \(http.statusCode): \(detail)")
        }
        return (http.statusCode, obj, setCookie)
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

/// Registers the intents as Siri phrases and exposes them in
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
        AppShortcut(
            intent: OpenChatIntent(),
            phrases: [
                "Open \(.applicationName) chat",
                "Open \(.applicationName) WebUI",
            ],
            shortTitle: "Open Chat",
            systemImageName: "bubble.left.and.bubble.right"
        )
        AppShortcut(
            intent: StackStatusIntent(),
            phrases: [
                "\(.applicationName) stack status",
                "Check \(.applicationName) status",
            ],
            shortTitle: "Stack Status",
            systemImageName: "heartbeat"
        )
        AppShortcut(
            intent: SwitchProfileIntent(),
            phrases: [
                "Switch \(.applicationName) profile",
            ],
            shortTitle: "Switch Profile",
            systemImageName: "person.crop.circle"
        )
        AppShortcut(
            intent: RunRoutineIntent(),
            phrases: [
                "Run \(.applicationName) routine",
            ],
            shortTitle: "Run Routine",
            systemImageName: "list.bullet.clipboard"
        )
    }
}
