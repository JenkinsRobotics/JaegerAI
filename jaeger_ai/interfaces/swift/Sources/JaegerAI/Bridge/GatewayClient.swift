import Foundation

/// Persistence-spine client for Jaeger Gateway (`:8810`).
///
/// Lists / activates agents and session handoffs via `GET|POST /v1/*`
/// without rewriting the desktop UI around the Python NDJSON bridge.
struct GatewayClient: Sendable {
    let baseURL: URL

    struct Failure: Error, LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }

    struct Agent: Decodable, Identifiable, Sendable {
        let id: String
        let name: String
        let kind: String
        let display_name: String?
        let role: String?
        let active: Bool?
        let switchable: Bool?
        let fundamentals_gated: Bool?
        let adapter: String?
        let endpoint: String?
        let port: Int?

        var displayName: String { display_name ?? name }
        var resolvedRole: String { role ?? kind }
    }

    struct Catalog: Decodable, Sendable {
        let model: String?
        let jaeger_native: [Agent]?
        let third_party: [Agent]?
        let fundamentals_fee_gated: Bool?
        let persistence_spine: String?
        let counts: [String: Int]?
        let agents: [Agent]?
        let lead: Agent?
        let specialists: [Agent]?
        let active: Agent?
    }

    struct SessionHandoff: Decodable, Sendable {
        let session_id: String
        let agent_id: String
        let previous_agent_id: String?
        let agent: Agent?
        let keep_history: Bool?
        let reason: String?
    }

    static let defaultBaseURL = URL(string: "http://127.0.0.1:8810")!

    static func fromEnvironment() -> GatewayClient {
        let raw = ProcessInfo.processInfo.environment["JAEGER_GATEWAY_URL"]?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if let raw, let url = URL(string: raw), url.host != nil {
            return GatewayClient(baseURL: url)
        }
        return GatewayClient(baseURL: defaultBaseURL)
    }

    /// Lightweight liveness probe. Avoids `[String: Any]` so Swift 6
    /// concurrency (Sendable) accepts the call from UI tasks.
    @discardableResult
    func health() async throws -> Bool {
        _ = try await request(path: "health")
        return true
    }

    /// `GET /v1/agents` — optional `kind` / `role` filters (`lead|specialist|runtime`).
    func listAgents(kind: String? = nil, role: String? = nil) async throws -> Catalog {
        var path = "v1/agents"
        var qs: [String] = []
        if let kind, !kind.isEmpty { qs.append("kind=\(kind)") }
        if let role, !role.isEmpty { qs.append("role=\(role)") }
        if !qs.isEmpty { path += "?" + qs.joined(separator: "&") }
        let data = try await request(path: path)
        return try JSONDecoder().decode(Catalog.self, from: data)
    }

    func activateAgent(id: String) async throws -> Agent {
        let encoded = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id
        let data = try await request(path: "v1/agents/\(encoded)/activate", method: "POST")
        return try JSONDecoder().decode(Agent.self, from: data)
    }

    /// `POST /v1/sessions/{id}/handoff`
    func handoffSession(
        sessionId: String,
        toAgentId: String,
        reason: String? = nil,
        keepHistory: Bool = true
    ) async throws -> SessionHandoff {
        let encoded = sessionId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? sessionId
        var body: [String: Any] = [
            "to_agent_id": toAgentId,
            "keep_history": keepHistory,
        ]
        if let reason, !reason.isEmpty { body["reason"] = reason }
        let data = try await request(
            path: "v1/sessions/\(encoded)/handoff",
            method: "POST",
            jsonBody: body
        )
        return try JSONDecoder().decode(SessionHandoff.self, from: data)
    }

    private func request(
        path: String,
        method: String = "GET",
        jsonBody: [String: Any]? = nil
    ) async throws -> Data {
        let url: URL
        if path.contains("?") {
            let base = baseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            guard let built = URL(string: base + "/" + path) else {
                throw Failure(message: "Invalid gateway URL path")
            }
            url = built
        } else {
            url = baseURL.appendingPathComponent(path)
        }
        var request = URLRequest(url: url, timeoutInterval: 8)
        request.httpMethod = method
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let jsonBody {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: jsonBody)
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            throw Failure(message: object?["error"] as? String ?? "Gateway request failed (\(path))")
        }
        return data
    }
}
