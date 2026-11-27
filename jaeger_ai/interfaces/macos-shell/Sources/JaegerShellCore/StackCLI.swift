// JaegerShellCore: `jaeger stack … --json` reply types.
// Ported from jaeger_ai/interfaces/swift/Sources/JaegerAI/Bridge/StackManager.swift:13-47 (Jenkins Robotics),
// made public + Equatable; `summary` and `restartArguments` added.
import Foundation

public struct StackServiceStatus: Decodable, Sendable, Equatable {
    public let id: String
    public let name: String
    public let label: String
    public let pid: Int?
    public let state: String
    public let rawState: String?
    public let ready: Bool
    public let configured: Bool
    public let port: Int?
    public let gitCommit: String?
    public let headCommit: String?
    public let stale: Bool

    enum CodingKeys: String, CodingKey {
        case id, name, label, pid, state
        case rawState = "raw_state"
        case ready, configured, port
        case gitCommit = "git_commit"
        case headCommit = "head_commit"
        case stale
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? id
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? id
        pid = try c.decodeIfPresent(Int.self, forKey: .pid)
        state = try c.decodeIfPresent(String.self, forKey: .state) ?? "unknown"
        rawState = try c.decodeIfPresent(String.self, forKey: .rawState)
        ready = try c.decodeIfPresent(Bool.self, forKey: .ready) ?? false
        configured = try c.decodeIfPresent(Bool.self, forKey: .configured) ?? true
        port = try c.decodeIfPresent(Int.self, forKey: .port)
        gitCommit = try c.decodeIfPresent(String.self, forKey: .gitCommit)
        headCommit = try c.decodeIfPresent(String.self, forKey: .headCommit)
        stale = try c.decodeIfPresent(Bool.self, forKey: .stale) ?? false
    }
}

public struct StackStatusReply: Decodable, Sendable {
    public let ok: Bool
    public let services: [StackServiceStatus]
}

public struct StackActionReply: Decodable, Sendable {
    public let ok: Bool
    public let step: String?
    public let error: String?
    public let services: [StackServiceStatus]?
}

public enum StackCLI {
    public static let upArguments = ["stack", "up", "--json"]
    public static let statusArguments = ["stack", "status", "--json"]
    public static let restartArguments = ["stack", "restart", "--json"]
    /// Ported from StackManager.swift:59-61 (`down`); used only by the production Stop (never in tests).
    public static let downArguments = ["stack", "down", "--json"]

    public static func decodeAction(_ data: Data) throws -> StackActionReply {
        try JSONDecoder().decode(StackActionReply.self, from: data)
    }

    public static func summary(_ reply: StackActionReply) -> String {
        let services = reply.services ?? []
        let ready = services.filter(\.ready).count
        var text = "ok=\(reply.ok) services=\(services.count) ready=\(ready)"
        if let step = reply.step { text += " step=\(step)" }
        if let error = reply.error { text += " error=\(error)" }
        return text
    }
}
