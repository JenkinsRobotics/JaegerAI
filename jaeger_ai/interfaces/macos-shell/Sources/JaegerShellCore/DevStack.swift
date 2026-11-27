// JaegerShellCore: stack mode + the dev/test stack (pure, unit-tested).
//
// Production uses `jaeger stack up|down --json` (launchd-backed) — never invoked by tests.
// Dev mode (dev build + JAEGER_SHELL_STACK_MODE=dev + JAEGER_SHELL_DEV_ROOT=<worktree>) runs the worktree
// gateway and the built main screen as the shell's OWN foreground child processes on 127.0.0.1, with an
// isolated JAEGER_STATE_DIR and a minimal environment (nothing inherited, so no 0.0.0.0 host vars), and
// stops them by their own PIDs. Same gateway command as Scripts/test-servers.sh.
import Foundation

public enum StackMode: Equatable, Sendable {
    case production
    case dev

    public static let envKey = "JAEGER_SHELL_STACK_MODE"

    /// Dev only in a dev build with JAEGER_SHELL_STACK_MODE=dev; anything else is production.
    public static func resolve(env: [String: String], isDevBuild: Bool) -> StackMode {
        isDevBuild && env[envKey]?.trimmingCharacters(in: .whitespaces).lowercased() == "dev" ? .dev : .production
    }
}

public enum DevStackError: Error, Equatable, Sendable {
    case notDevMode
    case missingRoot
    case notAWorktree(String)
    case badPort(String)
    case reservedPort(Int)
    case unsafeStateDir(String)
    case missingExecutable(String)

    public var message: String {
        switch self {
        case .notDevMode: return "dev stack needs a dev build and JAEGER_SHELL_STACK_MODE=dev"
        case .missingRoot: return "JAEGER_SHELL_DEV_ROOT (the worktree root) is required"
        case .notAWorktree(let p): return "not a Jaeger worktree (no jaeger_ai/core/gateway/server.py): \(p)"
        case .badPort(let p): return "port must be 1024-65535: \(p)"
        case .reservedPort(let p): return "port \(p) is reserved (production/other stacks) and never used by the dev stack"
        case .unsafeStateDir(let p): return "state dir must be outside ~/.jaeger: \(p)"
        case .missingExecutable(let p): return "not executable: \(p)"
        }
    }
}

public struct ChildCommand: Equatable, Sendable {
    public let executable: String
    public let arguments: [String]
    public let environment: [String: String]
    public let workingDirectory: String
}

public struct DevStackConfig: Equatable, Sendable {
    public let root: String
    public let python: String
    public let node: String
    public let stateDir: String
    public let gatewayPort: Int
    public let uiPort: Int
    public let uiDir: String
    public let uiDist: String

    /// 43418 = Gateway bot / IDE test gateway; 33418 = production gateway; 8790 = old WebUI; 8793 = webhook.
    public static let reservedPorts: Set<Int> = [43418, 33418, 8790, 8793]
    public static let defaultGatewayPort = 43428
    public static let defaultUIPort = 18800

    public var gatewayOrigin: LoopbackOrigin { LoopbackOrigin(port: gatewayPort) }
    public var uiOrigin: LoopbackOrigin { LoopbackOrigin(port: uiPort) }

    public static func resolve(env: [String: String], home: String, isDevBuild: Bool,
                               fileExists: (String) -> Bool, isExecutable: (String) -> Bool)
        -> Result<DevStackConfig, DevStackError>
    {
        guard StackMode.resolve(env: env, isDevBuild: isDevBuild) == .dev else { return .failure(.notDevMode) }
        func value(_ key: String) -> String? {
            env[key].map { $0.trimmingCharacters(in: .whitespaces) }.flatMap { $0.isEmpty ? nil : $0 }
        }
        guard let rawRoot = value("JAEGER_SHELL_DEV_ROOT") else { return .failure(.missingRoot) }
        let root = URL(fileURLWithPath: rawRoot).standardizedFileURL.path
        guard fileExists(root + "/jaeger_ai/core/gateway/server.py") else { return .failure(.notAWorktree(root)) }
        func port(_ key: String, _ fallback: Int) -> Result<Int, DevStackError> {
            guard let raw = value(key) else { return .success(fallback) }
            guard let p = Int(raw), (1024...65535).contains(p) else { return .failure(.badPort(raw)) }
            return .success(p)
        }
        let gw: Int, ui: Int
        switch port("JAEGER_SHELL_DEV_GATEWAY_PORT", defaultGatewayPort) { case .success(let p): gw = p; case .failure(let e): return .failure(e) }
        switch port("JAEGER_SHELL_DEV_UI_PORT", defaultUIPort) { case .success(let p): ui = p; case .failure(let e): return .failure(e) }
        for p in [gw, ui] where reservedPorts.contains(p) { return .failure(.reservedPort(p)) }
        guard gw != ui else { return .failure(.badPort("gateway and main-screen ports must differ")) }
        let state = URL(fileURLWithPath: value("JAEGER_SHELL_DEV_STATE_DIR") ?? home + "/.cache/jaeger/ui-rebuild-test-state")
            .standardizedFileURL.path
        let jaegerHome = home + "/.jaeger"
        guard state != jaegerHome, !state.hasPrefix(jaegerHome + "/"), state != home else { return .failure(.unsafeStateDir(state)) }
        let python = value("JAEGER_SHELL_DEV_PYTHON") ?? home + "/.jaeger/venv/bin/python"
        let node = value("JAEGER_SHELL_DEV_NODE") ?? "/opt/homebrew/bin/node"
        for exe in [python, node] where !isExecutable(exe) { return .failure(.missingExecutable(exe)) }
        return .success(DevStackConfig(
            root: root, python: python, node: node, stateDir: state, gatewayPort: gw, uiPort: ui,
            uiDir: root + "/jaeger_ai/interfaces/ui",
            uiDist: value("JAEGER_SHELL_DEV_UI_DIST") ?? home + "/.cache/jaeger/ui-rebuild-mainscreen/dist"))
    }

    private func baseEnvironment(home: String) -> [String: String] {
        ["HOME": home, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin", "LANG": "en_US.UTF-8"]
    }

    /// Same as Scripts/test-servers.sh: worktree gateway, loopback, isolated state, no background producers.
    public func gatewayCommand(home: String) -> ChildCommand {
        var env = baseEnvironment(home: home)
        env["JAEGER_STATE_DIR"] = stateDir
        // Explicit token dir: caller_auth then never falls back to the operator's Keychain items.
        env["JAEGER_CALLER_TOKEN_DIR"] = stateDir + "/caller_tokens"
        env["JAEGER_TEST_HEADLESS"] = "1"
        env["PYTHONPATH"] = root
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return ChildCommand(executable: python,
                            arguments: ["-m", "jaeger_ai.core.gateway.server", "--host", "127.0.0.1", "--port", String(gatewayPort)],
                            environment: env, workingDirectory: root)
    }

    /// The built main screen via `vite preview`; its /v1 and /api proxy to the dev gateway (loopback).
    public func uiCommand(home: String) -> ChildCommand {
        var env = baseEnvironment(home: home)
        // interfaces/ui/vite.config.ts reads JAEGER_WEBUI_URL (it was JAEGER_UI_PROXY_TARGET); set both.
        env["JAEGER_WEBUI_URL"] = gatewayOrigin.string
        env["JAEGER_UI_PROXY_TARGET"] = gatewayOrigin.string
        return ChildCommand(executable: node,
                            arguments: [uiDir + "/node_modules/vite/bin/vite.js", "preview", "--outDir", uiDist,
                                        "--host", "127.0.0.1", "--port", String(uiPort), "--strictPort"],
                            environment: env, workingDirectory: uiDir)
    }
}
