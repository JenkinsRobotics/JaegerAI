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
        // Immediately notify with current status
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
        
        var request = URLRequest(url: url)
        request.timeoutInterval = 5
        
        // Add auth token if available
        if let token = ShellEnvironment.callerToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        
        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self = self else { return }
                
                if let error = error {
                    self.updateStatus(.init(
                        state: .error,
                        currentTask: "Gateway unreachable",
                        model: nil,
                        sessionId: nil,
                        timestamp: Date()
                    ))
                    return
                }
                
                guard let data = data,
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                    self.updateStatus(.init(
                        state: .error,
                        currentTask: "Invalid response",
                        model: nil,
                        sessionId: nil,
                        timestamp: Date()
                    ))
                    return
                }
                
                self.parseHealth(json)
            }
        }.resume()
    }
    
    private func parseHealth(_ json: [String: Any]) {
        // Extract status info
        let status = json["status"] as? String ?? "unknown"
        let model = json["model"] as? String
        let diagnostics = json["diagnostics"] as? [String: Any]
        let ownerRuntime = diagnostics?["owner_runtime"] as? [String: Any]
        let resident = ownerRuntime?["resident"] as? Bool ?? false
        let executionVerified = ownerRuntime?["execution_verified"] as? Bool ?? true
        
        // Determine state
        let state: AgentState
        if status != "ok" {
            state = .error
        } else if !resident {
            state = .idle
        } else if !executionVerified {
            state = .thinking
        } else {
            state = .idle
        }
        
        let newStatus = Status(
            state: state,
            currentTask: state == .thinking ? "Processing…" : nil,
            model: model,
            sessionId: nil,
            timestamp: Date()
        )
        
        updateStatus(newStatus)
    }
    
    private func updateStatus(_ newStatus: Status) {
        let previousState = currentStatus.state
        currentStatus = newStatus
        
        // Notify observers
        for observer in observers.values {
            observer(newStatus)
        }
        
        // Log state changes
        if previousState != newStatus.state {
            shellLog("[agent-status] \(previousState.rawValue) → \(newStatus.state.rawValue)")
        }
    }
}

// MARK: - ShellEnvironment Extension

extension ShellEnvironment {
    /// Get caller token for Gateway auth
    static func callerToken() -> String? {
        // Try environment
        if let token = ProcessInfo.processInfo.environment["JAEGER_CALLER_TOKEN"] {
            return token
        }
        // Try keychain
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "ai.jaeger.gateway.caller",
            kSecAttrAccount as String: "menubar",
            kSecReturnData as String: true,
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecSuccess, let data = result as? Data {
            return String(data: data, encoding: .utf8)
        }
        return nil
    }
}
