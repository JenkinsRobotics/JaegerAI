import Foundation

/// Navigation data only. Never a URL, tool request, permission or execution instruction.
public enum NotificationDestination: Equatable, Sendable {
    case inbox
    case conversation(String)

    public static func validSession(_ id: String) -> Bool {
        !id.isEmpty && id.utf8.count <= 256 && id.utf8.allSatisfy {
            (65...90).contains($0) || (97...122).contains($0) || (48...57).contains($0) || [45, 46, 58, 95].contains($0)
        }
    }

    public var payload: [String: String] {
        switch self {
        case .inbox: return ["target": "notifications"]
        case .conversation(let id): return ["target": "conversation", "session_id": id]
        }
    }

    public static func parse(_ value: [AnyHashable: Any]) -> NotificationDestination? {
        if value.count == 1, value["target"] as? String == "notifications" { return .inbox }
        if value.count == 2, value["target"] as? String == "conversation",
           let id = value["session_id"] as? String, validSession(id) { return .conversation(id) }
        return nil
    }
}

/// Single ephemeral UI click, retained until the renderer acknowledges its identity.
/// This is not an execution/request queue and is never persisted as agent state.
public final class NotificationNavigationMailbox {
    private var pending: (id: UUID, destination: NotificationDestination)?
    public init() {}
    public func receive(_ destination: NotificationDestination, id: UUID = UUID()) {
        pending = (id, destination)
    }
    public var payload: [String: Any]? {
        guard let pending else { return nil }
        return ["id": pending.id.uuidString, "destination": pending.destination.payload]
    }
    public func acknowledge(_ id: String) -> Bool {
        guard pending?.id.uuidString == id else { return false }
        pending = nil
        return true
    }
}

/// No numeric count: Gateway proves retained presence, absence, or an incomplete scan.
public enum ActivityBadgeState: String, Equatable, Sendable {
    case off, present, absent, unknown
}
