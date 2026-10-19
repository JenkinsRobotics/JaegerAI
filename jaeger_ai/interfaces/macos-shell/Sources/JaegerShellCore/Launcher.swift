// JaegerShellCore: `jaeger` CLI launcher resolution.
// Ported (adapted) from jaeger_ai/interfaces/swift/Sources/JaegerAI/Bridge/BridgeProcess.swift:215-239
// (`jaegerPath()`, Jenkins Robotics). Changes: pure + testable; JAEGER_BRIDGE_CMD dropped (old NDJSON
// bridge only); every candidate must be executable (the old fallback returned a path that may not
// exist). Installed CLI fallbacks retired during frontend cleanup; venv selects the wrapper interpreter.
import Foundation

public enum LauncherResolver {
    public static func candidates(env: [String: String], plistLauncher: String?, bundlePath: String, home: String) -> [String] {
        // Development bundles pin their source wrapper. A missing pin must fail,
        // never select an older installed CLI or a nearby scratch checkout.
        if let configured = plistLauncher, !configured.isEmpty {
            return [configured.hasPrefix("~/") ? (home as NSString).appendingPathComponent(String(configured.dropFirst(2))) : configured]
        }
        let repo = env["JAEGER_REPO"].flatMap { $0.isEmpty ? nil : $0 } ?? (home as NSString).appendingPathComponent("GitHub/JaegerAI")
        return [(repo as NSString).appendingPathComponent("jaeger")]

    }

    public static func resolve(env: [String: String], plistLauncher: String?, bundlePath: String, home: String,
                               isExecutable: (String) -> Bool) -> String? {
        candidates(env: env, plistLauncher: plistLauncher, bundlePath: bundlePath, home: home).first(where: isExecutable)
    }
}
