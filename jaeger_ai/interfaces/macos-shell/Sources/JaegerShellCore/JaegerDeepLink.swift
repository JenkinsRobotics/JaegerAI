import Foundation

/// Original local navigation URLs. Never an execution, external URL or credential contract.
public enum JaegerDeepLink {
    public static func destination(_ url: URL) -> NotificationDestination? {
        guard let parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
              parts.scheme?.lowercased() == "jaeger", parts.user == nil, parts.password == nil,
              parts.port == nil, parts.query == nil, parts.fragment == nil else { return nil }
        switch parts.host?.lowercased() {
        case "notifications":
            guard parts.percentEncodedPath.isEmpty || parts.percentEncodedPath == "/" else { return nil }
            return .inbox
        case "conversation":
            let path = parts.percentEncodedPath.split(separator: "/", omittingEmptySubsequences: false)
            guard path.count == 2, path[0].isEmpty,
                  let id = String(path[1]).removingPercentEncoding,
                  id != ".", id != "..", NotificationDestination.validSession(id) else { return nil }
            return .conversation(id)
        default: return nil
        }
    }
}
