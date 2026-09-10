import Foundation

/// Persistence-spine client for Jaeger Gateway (`:8810`).
///
/// Smallest hook so the Mac app can list / activate agents via
/// `GET|POST /v1/agents` without rewriting the desktop UI around the
/// Python NDJSON bridge. When the gateway is stopped, callers treat
/// failures as "unavailable" and keep using the existing bridge path.
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
        let active: Bool?
        let switchable: Bool?
        let fundamentals_gated: Bool?
        let adapter: String?
        let endpoint: String?
        let port: Int?

        var displayName: String { display_name ?? name }
    }

    struct Catalog: Decodable, Sendable {
        let jaeger_native: [Agent]?
        let third_party: [Agent]?
        let fundamentals_fee_gated: Bool?
        let persistence_spine: String?
        let counts: [String: Int]?
        let agents: [Agent]?
    }

    /// Default local gateway — same port as `jaeger_ai.core.gateway.server`.
    static let defaultBaseURL = URL(string: "http://127.0.0.1:8810")!

    static func fromEnvironment() -> GatewayClient {
        let raw = ProcessInfo.processInfo.environment["JAEGER_GATEWAY_URL"]?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if let raw, let url = URL(string: raw), url.host != nil {
            return GatewayClient(baseURL: url)
        }
        return GatewayClient(baseURL: defaultBaseURL)
    }

    func health() async throws -> [String: Any] {
        let data = try await request(path: "health")
        let object = try JSONSerialization.jsonObject(with: data)
        guard let dict = object as? [String: Any] else {
            throw Failure(message: "Gateway health returned non-object JSON")
        }
        return dict
    }

    /// `GET /v1/agents` — native + third-party catalog.
    func listAgents(kind: String? = nil) async throws -> Catalog {
        var path = "v1/agents"
        if let kind, !kind.isEmpty {
            path += "?kind=\(kind)"
        }
        let data = try await request(path: path)
        return try JSONDecoder().decode(Catalog.self, from: data)
    }

    func activateAgent(id: String) async throws -> Agent {
        let encoded = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id
        let data = try await request(path: "v1/agents/\(encoded)/activate", method: "POST")
        return try JSONDecoder().decode(Agent.self, from: data)
    }

    private func request(path: String, method: String = "GET") async throws -> Data {
        let url: URL
        if path.contains("?") {
            // Query string — appendPathComponent would escape '?'.
            let base = baseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            guard let built = URL(string: base + "/" + path) else {
                throw Failure(message: "Invalid gateway URL path")
            }
            url = built
        } else {
            url = baseURL.appendingPathComponent(path)
        }
        var request = URLRequest(url: url, timeoutInterval: 5)
        request.httpMethod = method
        request.cachePolicy = .reloadIgnoringLocalCacheData
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            throw Failure(message: object?["error"] as? String ?? "Gateway request failed (\(path))")
        }
        return data
    }
}
