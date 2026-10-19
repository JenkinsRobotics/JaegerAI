// JaegerShellCore: the lifecycle-lease contract of jaeger_ai/core/runtime/lifecycle_lease.py, mirrored for
// the shell (path resolution, file body, decision) so it can be unit-tested. The beat itself is
// JaegerShell/LeaseBeat.swift (ported from interfaces/swift StackManager.swift:104-181).
import Foundation

public enum LeaseDecision: Equatable, Sendable {
    case noLease          // lifecycle_lease.py:66-67  no file: "no lease issued", privileged work allowed, no shutdown
    case alive            // :81
    case suspended        // :79-80  heartbeat missed (age > SUSPEND_AFTER_S)
    case shutdown(String) // :71-78  foreign / unreadable / owner disappeared (age > SHUTDOWN_GRACE_S)

    public var label: String {
        switch self {
        case .noLease: return "no_lease"
        case .alive: return "alive"
        case .suspended: return "suspended"
        case .shutdown(let reason): return "shutdown: \(reason)"
        }
    }
}

/// How the shell gives the lease up.
public enum LeaseRetire: String, Sendable {
    /// Default and the only mode in production builds. Remove the lease file: the contract reads a missing
    /// file as "no lease issued" (allowed, never a shutdown), so the stack outlives the window.
    case remove
    /// The old app's retire (interfaces/swift StackManager.swift:133-143): write beat_at 0, which the Gateway
    /// reads as "lifecycle owner disappeared" and answers with a controlled shutdown (stack down for the
    /// launchd Gateway). Dev builds only (JAEGER_SHELL_LEASE_RETIRE=expire), for the headless comparison.
    case expire

    public static let envKey = "JAEGER_SHELL_LEASE_RETIRE"
    public static func resolve(env: [String: String], isDevBuild: Bool) -> LeaseRetire {
        guard isDevBuild, env[envKey]?.trimmingCharacters(in: .whitespaces).lowercased() == "expire" else { return .remove }
        return .expire
    }
    /// Production builds can never expire the lease, whatever the caller asks for.
    public static func allowed(_ requested: LeaseRetire, isDevBuild: Bool) -> LeaseRetire {
        isDevBuild ? requested : .remove
    }
}

public enum LeaseContract {
    public static let owner = "menubar"                       // lifecycle_lease.py:53-54
    public static let suspendAfter: TimeInterval = 5          // :19 SUSPEND_AFTER_S
    public static let shutdownGrace: TimeInterval = 15        // :20 SHUTDOWN_GRACE_S
    /// "The menu bar beats faster than this" (:17). The old app beat every 5 s, i.e. right at SUSPEND_AFTER_S.
    public static let beatInterval: TimeInterval = 2
    public static let envKey = "JAEGER_LIFECYCLE_LEASE"       // :16

    /// Same order as LifecycleLease.load() (:43-50) + operator_state_root() (instance.py:246-268):
    /// JAEGER_LIFECYCLE_LEASE, JAEGER_STATE_DIR, JAEGER_HOME/.jaeger_ai, ~/.jaeger; then control/lifecycle-lease.json.
    public static func path(env: [String: String], home: String) -> String {
        func value(_ key: String) -> String? {
            guard let raw = env[key]?.trimmingCharacters(in: .whitespacesAndNewlines), !raw.isEmpty else { return nil }
            return expand(raw, home: home)
        }
        if let explicit = value(envKey) { return explicit }
        let root = value("JAEGER_STATE_DIR") ?? value("JAEGER_HOME").map { $0 + "/.jaeger_ai" } ?? home + "/.jaeger"
        return root + "/control/lifecycle-lease.json"
    }

    /// Lease inside a given state dir (the dev/test stack's isolated JAEGER_STATE_DIR).
    public static func path(stateDir: String) -> String { stateDir + "/control/lifecycle-lease.json" }

    /// The operator's real lease. Headless checks refuse to touch it.
    public static func realOperatorPath(home: String) -> String { home + "/.jaeger/control/lifecycle-lease.json" }

    /// Byte-compatible with LifecycleLease.beat (json.dumps(sort_keys=True)) and the old Swift beat.
    public static func body(beatAt: TimeInterval) -> String {
        String(format: "{\"beat_at\": %.6f, \"owner\": \"menubar\"}\n", beatAt)
    }

    public static func beatAt(contents: String) -> Double? {
        guard let obj = try? JSONSerialization.jsonObject(with: Data(contents.utf8)) as? [String: Any] else { return nil }
        return (obj["beat_at"] as? NSNumber)?.doubleValue
    }

    /// Mirror of LifecycleLease.decide (:65-81). `contents == nil` means no file.
    public static func decide(contents: String?, now: TimeInterval) -> LeaseDecision {
        guard let contents else { return .noLease }
        guard let obj = try? JSONSerialization.jsonObject(with: Data(contents.utf8)) as? [String: Any],
              let beat = (obj["beat_at"] as? NSNumber)?.doubleValue
        else { return .shutdown("lifecycle lease is unreadable") }
        guard obj["owner"] as? String == owner else { return .shutdown("lifecycle lease is not the menu bar") }
        let age = now - beat
        if age > shutdownGrace { return .shutdown("lifecycle owner disappeared") }
        if age > suspendAfter { return .suspended }
        return .alive
    }

    static func expand(_ raw: String, home: String) -> String {
        if raw == "~" { return home }
        if raw.hasPrefix("~/") { return home + raw.dropFirst(1) }
        return raw
    }
}
