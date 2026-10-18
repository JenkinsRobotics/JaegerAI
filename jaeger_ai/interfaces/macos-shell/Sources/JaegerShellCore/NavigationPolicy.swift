// JaegerShellCore: loopback-only navigation and resource policy for the web view.
import Foundation

public enum NavigationDecision: Sendable, Equatable { case allow, openExternally, block }

public enum NavigationPolicy {
    public static func decide(_ url: URL?, allowed: LoopbackOrigin) -> NavigationDecision {
        guard let url, let scheme = url.scheme?.lowercased() else { return .block }
        switch scheme {
        case "about":
            return url.absoluteString == "about:blank" ? .allow : .block
        case "http":
            if url.host == allowed.host, (url.port ?? 80) == allowed.port { return .allow }
            return .openExternally
        case "https", "mailto":
            return .openExternally
        default:
            return .block
        }
    }

    /// WKContentRuleList JSON: block every resource load, then re-allow the
    /// one loopback origin (http + ws) and local data:/blob:/about: URLs.
    /// WebKit url-filter regexes have no disjunction (`|`), so each scheme is its own rule.
    public static func contentRuleListJSON(allowed: LoopbackOrigin) -> String {
        let p = allowed.port
        return """
        [
          {"trigger":{"url-filter":".*"},"action":{"type":"block"}},
          {"trigger":{"url-filter":"^http://127\\\\.0\\\\.0\\\\.1:\(p)/"},"action":{"type":"ignore-previous-rules"}},
          {"trigger":{"url-filter":"^ws://127\\\\.0\\\\.0\\\\.1:\(p)/"},"action":{"type":"ignore-previous-rules"}},
          {"trigger":{"url-filter":"^data:"},"action":{"type":"ignore-previous-rules"}},
          {"trigger":{"url-filter":"^blob:"},"action":{"type":"ignore-previous-rules"}},
          {"trigger":{"url-filter":"^about:"},"action":{"type":"ignore-previous-rules"}}
        ]
        """
    }
}
