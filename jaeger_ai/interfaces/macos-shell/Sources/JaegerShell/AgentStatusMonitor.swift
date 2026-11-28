// AgentStatusMonitor.swift — Monitors Jaeger agent state and updates UI
// Polls the Gateway health endpoint and broadcasts status to menu bar, pill, etc.

import Foundation
import JaegerShellCore

/// Agent status monitor — polls Gateway and notifies observers of state changes.
final class AgentStatusMonitor {

    enum AgentState: String {
        case idle
        case thinking
        case working
        case waiting
        case error
        case disconnected
    }

    struct Status {
        let state: AgentState
        let currentTask: String?
        let model: String?
        let sessionId: String?
        let timestamp: Date
    }

    // MARK: - Singleton

    static let shared = AgentStatusMonitor()

    private init() {}

    // MARK: - Properties

    private var timer: Timer?
    private var currentStatus = Status(
        state: .disconnected,
        currentTask: nil,
        model: nil,
        sessionId: nil,
        timestamp: Date()
    )
    private var observers: [UUID: (Status) -> Void] = [:]
    private let pollInterval: TimeInterval = 5.0

    // MARK: - Public API

    /// Start monitoring the Gateway
    func start(gatewayURL: String = "http://127.0.0.1:33418") {
        stop()

        // Initial poll
        poll(gatewayURL: gatewayURL)

        // Start timer
        timer = Timer.scheduledTimer(withTimeInterval: pollInterval, repeats: true) { [weak self] _ in
            self?.poll(gatewayURL: gatewayURL)
        }
    }

    /// Stop monitoring
    func stop() {
        timer?.invalidate()
        timer = nil
    }

    /// Get current status
    var status: Status { currentStatus }

    /// Subscribe to status changes
    @discardableResult
    func observe(_ observer: @escaping (Status) -> Void) -> UUID {
        let id = UUID()
        observers[id] = observer
        observer(currentStatus)
        return id
    }

    /// Unsubscribe
    func removeObserver(_ id: UUID) {
        observers.removeValue(forKey: id)
    }

    // MARK: - Private

    private func poll(gatewayURL: String) {
        guard let url = URL(string: gatewayURL + "/health") else { return }

        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 5)

        if let token = ShellEnvironment.callerToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        URLSession(configuration: .ephemeral).dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self else { return }

                if error != nil {
                    self.updateStatus(.init(
                        state: .disconnected,
                        currentTask: "Gateway unreachable",
                        model: nil,
                        sessionId: nil,
                        timestamp: Date()
                    ))
                    return
                }

                let code = (response as? HTTPURLResponse)?.statusCode
                let report = GatewayHealth.parse(statusCode: code, data: data)
                let json = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
                self.applyHealth(report, json: json)
            }
        }.resume()
    }

    private func applyHealth(_ report: GatewayHealthReport, json: [String: Any]?) {
        let diagnostics = json?["diagnostics"] as? [String: Any]
        let ownerRuntime = diagnostics?["owner_runtime"] as? [String: Any]
        let resident = ownerRuntime?["resident"] as? Bool ?? false
        let executionVerified = ownerRuntime?["execution_verified"] as? Bool ?? true

        let state: AgentState
        switch report.state {
        case .offline:
            state = .disconnected
        case .degraded:
            state = .error
        case .online:
            if resident && !executionVerified {
                state = .thinking
            } else {
                state = .idle
            }
        }

        let newStatus = Status(
            state: state,
            currentTask: state == .thinking ? "Processing…" : nil,
            model: report.model,
            sessionId: nil,
            timestamp: Date()
        )
        updateStatus(newStatus)
    }

    private func updateStatus(_ newStatus: Status) {
        let previousState = currentStatus.state
        currentStatus = newStatus

        for observer in observers.values {
            observer(newStatus)
        }

        if previousState != newStatus.state {
            shellLog("[agent-status] \(previousState.rawValue) → \(newStatus.state.rawValue)")
        }
    }
}

// MARK: - ShellEnvironment Extension

extension ShellEnvironment {
    /// Get optional caller token for Gateway auth without triggering Keychain prompts.
    static func callerToken() -> String? {
        let env = ProcessInfo.processInfo.environment
        if let token = env["JAEGER_CALLER_TOKEN"]?.trimmingCharacters(in: .whitespacesAndNewlines), !token.isEmpty {
            return token
        }
        let root = env["JAEGER_STATE_DIR"].map { ($0 as NSString).expandingTildeInPath }
            ?? (NSHomeDirectory() as NSString).appendingPathComponent(".jaeger")
        let path = (root as NSString).appendingPathComponent("caller_tokens/menubar.token")
        guard let raw = try? String(contentsOfFile: path, encoding: .utf8) else { return nil }
        let token = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return token.isEmpty ? nil : token
    }
}
