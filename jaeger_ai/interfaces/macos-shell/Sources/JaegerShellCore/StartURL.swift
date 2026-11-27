// JaegerShellCore: start URL resolution with a dev-only, loopback-validated override.
import Foundation

public struct LoopbackOrigin: Sendable, Equatable {
    public let port: Int
    public var host: String { "127.0.0.1" }
    public var string: String { "http://127.0.0.1:\(port)" }
    public init(port: Int) { self.port = port }
}

public enum StartURL {
    /// Jaeger WebUI: serves the new UI at `/` and proxies its API calls to the gateway with its own
    /// caller token. The gateway origin answers `/` with 401, so it cannot be the main screen.
    public static let defaultWebUI = LoopbackOrigin(port: 8790)
    public static let defaultMainScreen = defaultWebUI
    /// Main-screen override (new UI). The legacy JAEGER_SHELL_WEBUI_URL is still accepted after it.
    public static let mainScreenEnvKey = "JAEGER_SHELL_UI_URL"
    public static let defaultGateway = LoopbackOrigin(port: 33418)
    public static let webUIEnvKey = "JAEGER_SHELL_WEBUI_URL"
    public static let webUIDefaultsKey = "JaegerShellWebUIURL"
    public static let gatewayEnvKey = "JAEGER_SHELL_GATEWAY_URL"
    public static let gatewayDefaultsKey = "JaegerShellGatewayURL"
    /// The stack-wide gateway variable the old app read (GatewayClient.swift:60, M1).
    public static let gatewaySharedEnvKey = "JAEGER_GATEWAY_URL"

    /// Gateway override from the environment: the shell-specific key wins, then JAEGER_GATEWAY_URL.
    /// The value still goes through `resolve` (dev build + loopback validation), unlike the old app,
    /// which accepted any host.
    /// Main-screen override from the environment: JAEGER_SHELL_UI_URL, then legacy JAEGER_SHELL_WEBUI_URL.
    public static func mainScreenEnvValue(_ env: [String: String]) -> String? {
        [mainScreenEnvKey, webUIEnvKey].lazy
            .compactMap { env[$0]?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { !$0.isEmpty }
    }

    public static func gatewayEnvValue(_ env: [String: String]) -> String? {
        [gatewayEnvKey, gatewaySharedEnvKey].lazy
            .compactMap { env[$0]?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { !$0.isEmpty }
    }

    public struct Resolution: Sendable, Equatable {
        public let origin: LoopbackOrigin
        public let override: String?
        public let rejected: String?
        public var url: URL { URL(string: origin.string + "/?host=macos")! }
        public init(origin: LoopbackOrigin, override: String?, rejected: String?) {
            self.origin = origin
            self.override = override
            self.rejected = rejected
        }
    }

    /// Accept only http://127.0.0.1:<1024-65535>[/] with no credentials.
    /// Query and fragment are ignored (dropped).
    public static func validate(_ raw: String) -> LoopbackOrigin? {
        guard let c = URLComponents(string: raw.trimmingCharacters(in: .whitespaces)),
              c.scheme == "http",
              c.host == "127.0.0.1",
              c.user == nil, c.password == nil,
              let port = c.port, (1024...65535).contains(port),
              c.path == "/" || c.path.isEmpty
        else { return nil }
        return LoopbackOrigin(port: port)
    }

    /// Resolve an origin. Overrides are honoured only in a dev build
    /// (Info.plist JaegerDevBuild == true); env wins over UserDefaults.
    public static func resolve(fallback: LoopbackOrigin, envValue: String?, defaultsValue: String?,
                               isDevBuild: Bool) -> Resolution {
        let raw = [envValue, defaultsValue].compactMap { $0 }.first { !$0.isEmpty }
        guard let raw else { return Resolution(origin: fallback, override: nil, rejected: nil) }
        guard isDevBuild else { return Resolution(origin: fallback, override: nil, rejected: raw) }
        guard let origin = validate(raw) else { return Resolution(origin: fallback, override: nil, rejected: raw) }
        return Resolution(origin: origin, override: origin.string + "/", rejected: nil)
    }
}
