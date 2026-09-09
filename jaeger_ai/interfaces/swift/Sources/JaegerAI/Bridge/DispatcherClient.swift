import Foundation

/// Both desktop and WebUI observe and control this same durable conversation.
struct DispatcherClient: Sendable {
    let baseURL: URL
    let apiKey: String

    struct Message: Decodable, Sendable {
        let id: String
        let role: String
        let text: String
        let ts: Double
    }
    struct Approval: Decodable, Sendable {
        let approval_id: String
        let description: String
        let choices: [String]
    }
    struct Tool: Decodable, Sendable {
        let event: String
        let tool: String?
    }
    struct Run: Decodable, Sendable {
        let tools: [Tool]?
        let run_id: String
        let status: String
        let error: String?
        let output: String
        let active: Bool?
        let execution_unknown: Bool?
        let created_at: Double?
        let approvals: [Approval]?
    }
    struct Report: Decodable, Sendable {
        let run_id: String
        let summary: String
        let status: String
    }
    struct Snapshot: Decodable, Sendable {
        let reports: [Report]?
        let messages: [Message]
        let revision: String
        let run: Run?
    }
    struct Failure: Error, LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }

    func request(_ action: String = "", body: [String: String]? = nil) async throws -> Data {
        let url = baseURL.appendingPathComponent("v1/dispatcher/conversation" + (action.isEmpty ? "" : "/" + action))
        var request = URLRequest(url: url, timeoutInterval: 20)
        request.setValue("Bearer " + apiKey, forHTTPHeaderField: "Authorization")
        request.cachePolicy = .reloadIgnoringLocalCacheData
        if let body {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(body)
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let response = response as? HTTPURLResponse, (200..<300).contains(response.statusCode) else {
            let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            throw Failure(message: object?["error"] as? String ?? "Dispatcher request failed")
        }
        return data
    }

    func snapshot() async throws -> Snapshot {
        try JSONDecoder().decode(Snapshot.self, from: await request())
    }

    /// Identity is created before sending and must be retained for any retry.
    func send(_ text: String, requestID: String) async throws -> Run {
        try JSONDecoder().decode(Run.self, from: await request("send", body: ["input": text, "request_id": requestID]))
    }
}
