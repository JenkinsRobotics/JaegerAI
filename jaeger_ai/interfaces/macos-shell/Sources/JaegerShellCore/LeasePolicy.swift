// Whether this shell process may hold the lifecycle lease at all. Only the installed app does by default:
// the installer copies the bundle to /Applications/Jaeger AI.app (interfaces/swift/Scripts/build-app.sh:357,364)
// and the CLI also accepts /Applications/JaegerAI.app (cli/verbs/lifecycle_verbs.py:146-147). Dev builds
// (.build/ui-rebuild/JaegerShell.app, Jaeger Dev.app) get no lease unless JAEGER_SHELL_LEASE=1 (kept for the
// headless lease checks). JAEGER_SHELL_NO_LEASE=1 always wins: no acquire, beat or retire, and no path resolved.
import Foundation

public enum LeasePolicy {
    public static let noLeaseKey = "JAEGER_SHELL_NO_LEASE"
    public static let optInKey = "JAEGER_SHELL_LEASE"
    public static let installedBundlePaths = ["/Applications/Jaeger AI.app", "/Applications/JaegerAI.app"]

    public enum Decision: Equatable, Sendable {
        case enabled(reason: String)
        case disabled(reason: String)
        public var isEnabled: Bool { if case .enabled = self { return true } else { return false } }
        public var reason: String { switch self { case .enabled(let r), .disabled(let r): return r } }
    }

    static func truthy(_ value: String?) -> Bool {
        guard let v = value?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(), !v.isEmpty else { return false }
        return ["1", "true", "yes", "on"].contains(v)
    }

    public static func isInstalledBundle(_ bundlePath: String) -> Bool {
        let p = (bundlePath as NSString).standardizingPath
        return installedBundlePaths.contains(p)
    }

    public static func decide(env: [String: String], bundlePath: String) -> Decision {
        if truthy(env[noLeaseKey]) { return .disabled(reason: noLeaseKey) }
        if isInstalledBundle(bundlePath) { return .enabled(reason: "installed app") }
        if truthy(env[optInKey]) { return .enabled(reason: "\(optInKey) opt-in") }
        return .disabled(reason: "not the installed app")
    }
}
