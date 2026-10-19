// JaegerShellCore: `jaeger` CLI launcher resolution.
// Ported (adapted) from jaeger_ai/interfaces/swift/Sources/JaegerAI/Bridge/BridgeProcess.swift:215-239
// (`jaegerPath()`, Jenkins Robotics). Changes: pure + testable; JAEGER_BRIDGE_CMD dropped (old NDJSON
// bridge only); every candidate must be executable (the old fallback returned a path that may not
// exist); extra fallbacks ~/.jaeger/venv/bin, /opt/homebrew/bin, /usr/local/bin.
import Foundation

public enum LauncherResolver {
    public static func candidates(env: [String: String], plistLauncher: String?, bundlePath: String, home: String) -> [String] {
        var out: [String] = []
        if let configured = plistLauncher, !configured.isEmpty {
            out.append(configured.hasPrefix("~/") ? (home as NSString).appendingPathComponent(String(configured.dropFirst(2))) : configured)
        }
        var dir = (bundlePath as NSString).deletingLastPathComponent
        for _ in 0..<8 where !dir.isEmpty {
            out.append((dir as NSString).appendingPathComponent("jaeger"))
            if dir == "/" { break }
            dir = (dir as NSString).deletingLastPathComponent
        }
        let repo = env["JAEGER_REPO"].flatMap { $0.isEmpty ? nil : $0 } ?? (home as NSString).appendingPathComponent("GitHub/JaegerAI")
        out.append((repo as NSString).appendingPathComponent("jaeger"))
        if let venv = env["JAEGER_VENV"], !venv.isEmpty { out.append((venv as NSString).appendingPathComponent("bin/jaeger")) }
        out.append((home as NSString).appendingPathComponent(".jaeger/venv/bin/jaeger"))
        out += ["/opt/homebrew/bin/jaeger", "/usr/local/bin/jaeger"]
        return out
    }

    public static func resolve(env: [String: String], plistLauncher: String?, bundlePath: String, home: String,
                               isExecutable: (String) -> Bool) -> String? {
        candidates(env: env, plistLauncher: plistLauncher, bundlePath: bundlePath, home: home).first(where: isExecutable)
    }
}
