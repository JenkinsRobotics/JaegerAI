// JaegerShellCore: start URL resolution with a dev-only, loopback-validated override.
import Foundation

public struct LoopbackOrigin: Sendable, Equatable {
    public let port: Int
    public var host: String { "127.0.0.1" }
    public var string: String { "http://127.0.0.1:\(port)" }
    public init(port: Int) { self.port = port }
}

public enum StartURL {
    public static let defaultWebUI = LoopbackOrigin(port: 8790)
    public static let defaultGateway = LoopbackOrigin(port: 33418)
    public static let webUIEnvKey = "JAEGER_SHELL_WEBUI_URL"
    public static let webUIDefaultsKey = "JaegerShellWebUIURL"
    public static let gatewayEnvKey = "JAEGER_SHELL_GATEWAY_URL"
    public static let gatewayDefaultsKey = "JaegerShellGatewayURL"

    public struct Resolution: Sendable, Equatable {
        public let origin: LoopbackOrigin
        public let override: String?
        public let rejected: String?
        public var url: URL { URL(string: origin.string + "/?host=macos")! }
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
