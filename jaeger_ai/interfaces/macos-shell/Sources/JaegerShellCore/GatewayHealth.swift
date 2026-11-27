// JaegerShellCore: modular Gateway /health parsing and optional legacy endpoint backoff policy.
import Foundation

public enum GatewayHealthState: String, Sendable, Equatable {
    case online
    case degraded
    case offline
}

public struct GatewayHealthReport: Sendable, Equatable {
    public let state: GatewayHealthState
    public let statusText: String
    public let model: String?
    public let allGreen: Bool
    public let gatewayOK: Bool
    public let webuiOK: Bool?

    public var isHealthy: Bool { state == .online }

    public init(state: GatewayHealthState, statusText: String, model: String?,
                allGreen: Bool, gatewayOK: Bool, webuiOK: Bool?) {
        self.state = state
        self.statusText = statusText
        self.model = model
        self.allGreen = allGreen
        self.gatewayOK = gatewayOK
        self.webuiOK = webuiOK
    }

    public static let offline = GatewayHealthReport(
        state: .offline, statusText: "not_running", model: nil,
        allGreen: false, gatewayOK: false, webuiOK: nil
    )
}

public enum GatewayHealth {
    /// Parses both the modular Gateway `/health` payload (`ok`, `status: "ok"`, `all_green: true`,
    /// `checks: {gateway, ollama, webui}`) and legacy `/health` payloads.
    public static func parse(statusCode: Int?, data: Data?) -> GatewayHealthReport {
        guard let code = statusCode else { return .offline }
        guard (200..<300).contains(code) else {
            return GatewayHealthReport(
                state: .offline, statusText: "http_\(code)", model: nil,
                allGreen: false, gatewayOK: false, webuiOK: nil
            )
        }
        guard let data, !data.isEmpty,
              let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            return GatewayHealthReport(
                state: .online, statusText: "running", model: nil,
                allGreen: true, gatewayOK: true, webuiOK: nil
            )
        }

        let model = (json["model"] as? String).flatMap { $0.isEmpty ? nil : $0 }
        let okFlag = json["ok"] as? Bool
        let allGreenFlag = json["all_green"] as? Bool
        let statusRaw = (json["status"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()

        let checks = json["checks"] as? [String: Any]
        let gatewayCheck = (checks?["gateway"] as? [String: Any])?["ok"] as? Bool
        let webuiCheck = (checks?["webui"] as? [String: Any])?["ok"] as? Bool

        let statusHealthy = statusRaw == "ok" || statusRaw == "healthy" || statusRaw == "running"
        let healthy = (allGreenFlag == true) || (okFlag == true) || statusHealthy
        let gatewayOK = gatewayCheck ?? healthy

        let state: GatewayHealthState = healthy ? .online : .degraded
        let statusText = healthy ? "running" : (statusRaw ?? "degraded")

        return GatewayHealthReport(
            state: state,
            statusText: statusText,
            model: model,
            allGreen: allGreenFlag ?? healthy,
            gatewayOK: gatewayOK,
            webuiOK: webuiCheck
        )
    }
}

public enum LiveTasksResponsePolicy {
    /// Missing/unimplemented legacy routes on the modular Gateway (e.g. GET /v1/live/tasks -> 404)
    /// must not spam retries or mark the shell offline.
    public static func shouldDisablePolling(statusCode: Int) -> Bool {
        statusCode == 404 || statusCode == 405 || statusCode == 501
    }
}
