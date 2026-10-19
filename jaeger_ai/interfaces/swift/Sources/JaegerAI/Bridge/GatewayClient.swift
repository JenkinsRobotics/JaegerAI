import Foundation

/// The menu-bar app's Gateway caller token (`menubar`).
///
/// Stored in the login Keychain (service `ai.jaeger.gateway.caller`) by
/// `jaeger auth init`. Read through `/usr/bin/security` — the tool that wrote
/// the item and is on its access list — so the app never triggers a Keychain
/// prompt and never stores the value anywhere else. Cached for 30 s.
enum GatewayCallerToken {
    static let service = "ai.jaeger.gateway.caller"
    static let caller = "menubar"
    private static let lock = NSLock()
    nonisolated(unsafe) private static var cached: (value: String, at: Date)?

    static func current() -> String? {
        lock.lock(); defer { lock.unlock() }
        if let cached, Date().timeIntervalSince(cached.at) < 30 { return cached.value }
        let value = read()
        cached = value.map { ($0, Date()) }
        return value
    }

    private static func read() -> String? {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/security")
        process.arguments = ["find-generic-password", "-s", service, "-a", caller, "-w"]
        let out = Pipe()
        process.standardOutput = out
        process.standardError = FileHandle.nullDevice
        do { try process.run() } catch { return nil }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else { return nil }
        let token = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        return token.isEmpty ? nil : token
    }

    /// Adds `Authorization: Bearer …` when a token exists. Without one the
    /// Gateway answers 401, which surfaces as a normal request failure.
    static func authorize(_ request: inout URLRequest) {
        if let token = current() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
    }
}

/// Where the Jaeger Gateway lives. Mirrors `jaeger_ai/contract/ports.py`
/// (`GATEWAY_PORT` default); a Python test
/// (`test_gateway_port_mirrors_agree_with_the_contract`) fails if they drift.
/// The pre-2026-10-17 port is retired; there is no fallback.
enum GatewayEndpoint {
    static let loopback = "127.0.0.1"
    static let currentPort = 33418
    static let currentURL = URL(string: "http://\(loopback):\(currentPort)")!

    static func resolve(
        _ environment: [String: String],
        reachable: (URL) -> Bool = acceptsConnection
    ) -> URL {
        let raw = environment["JAEGER_GATEWAY_URL"]?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if let raw, !raw.isEmpty, let url = URL(string: raw), url.host != nil {
            return url
        }
        var current = currentURL
        if let portText = environment["JAEGER_GATEWAY_PORT"], let port = Int(portText),
           let url = URL(string: "http://\(loopback):\(port)") {
            current = url
        }
        return current
    }

    /// Blocking loopback TCP connect. Loopback refuses or accepts at once, so
    /// this does not stall the caller.
    static func acceptsConnection(_ url: URL) -> Bool {
        guard let host = url.host, let port = url.port else { return false }
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        guard fd >= 0 else { return false }
        defer { close(fd) }
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = in_port_t(UInt16(port).bigEndian)
        guard inet_pton(AF_INET, host, &addr.sin_addr) == 1 else { return false }
        let result = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        return result == 0
    }
}

/// Persistence-spine client for Jaeger Gateway (`GatewayEndpoint`).
///
/// Lists / activates agents and session handoffs via `GET|POST /v1/*`
/// without rewriting the desktop UI around the Python NDJSON bridge.
struct GatewayClient: Sendable {
    let baseURL: URL

    struct Failure: Error, LocalizedError {
        let message: String
        var statusCode: Int? = nil
        var errorDescription: String? { message }
    }

    struct RuntimeSkill: Decodable, Identifiable, Sendable {
        let name: String
        let category: String
        let description: String
        let lifecycle: String
        var id: String { category + "/" + name }
    }

    struct RuntimeSkills: Decodable, Sendable {
        let skills: [RuntimeSkill]
    }

    func runtimeSkills() async throws -> [RuntimeSkill] {
        let data = try await request(path: "v1/runtime/skills")
        return try JSONDecoder().decode(RuntimeSkills.self, from: data).skills
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

    static let defaultBaseURL = GatewayEndpoint.currentURL

    /// `JAEGER_GATEWAY_URL` if set; else `JAEGER_GATEWAY_PORT`; else the contract port.
    static func fromEnvironment(
        _ environment: [String: String] = ProcessInfo.processInfo.environment,
        reachable: (URL) -> Bool = GatewayEndpoint.acceptsConnection
    ) -> GatewayClient {
        GatewayClient(baseURL: GatewayEndpoint.resolve(environment, reachable: reachable))
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

    /// Internal (not private) so the session/stream half in
    /// ``GatewaySessions.swift`` reuses this one request path — same
    /// timeout, same error unwrapping, same URL building — instead of
    /// growing a second, subtly different HTTP layer.
    func request(
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
        GatewayCallerToken.authorize(&request)
        if let jsonBody {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: jsonBody)
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            throw Failure(message: object?["error"] as? String ?? "Gateway request failed (\(path))", statusCode: (response as? HTTPURLResponse)?.statusCode)
        }
        return data
    }
}
