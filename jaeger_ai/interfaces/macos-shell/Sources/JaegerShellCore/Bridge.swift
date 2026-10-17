// JaegerShellCore: the `jaeger` JS⇄native bridge contract (pure, unit-tested).
//
// JS→native: window.webkit.messageHandlers.jaeger.postMessage({id, type, payload}),
// normally through window.jaegerNative.post(type, payload) → Promise (user script below).
// native→JS: window.dispatchEvent(new CustomEvent("jaeger:native", {detail})), including
// {type:"reply", id, ok, result|error}.
// Messages are accepted only from the main frame of the effective loopback WebUI origin.
// No eval, no command execution, no file contents; `stack.up` is deliberately not exposed.
import CoreFoundation
import Foundation

public struct BridgeFrame: Sendable, Equatable {
    public let isMainFrame: Bool
    public let scheme: String
    public let host: String
    public let port: Int
    public init(isMainFrame: Bool, scheme: String, host: String, port: Int) {
        self.isMainFrame = isMainFrame
        self.scheme = scheme
        self.host = host
        self.port = port
    }
    public var description: String { "\(scheme)://\(host):\(port) main=\(isMainFrame)" }
}

public enum BridgeOriginPolicy {
    public static func accepts(_ frame: BridgeFrame, allowed: LoopbackOrigin) -> Bool {
        frame.isMainFrame && frame.scheme.lowercased() == "http" && frame.host == allowed.host
            && frame.port == allowed.port
    }
}

public enum BridgeError: Error, Equatable, Sendable {
    case badMessage
    case unknownType(String)
    case invalidPayload(String)

    public var message: String {
        switch self {
        case .badMessage: return "bad_message"
        case .unknownType(let type): return "unknown_type: \(type)"
        case .invalidPayload(let detail): return "invalid_payload: \(detail)"
        }
    }
}

public struct BridgeRequest {
    public let id: String
    public let type: String
    public let payload: [String: Any]

    public static func parse(_ body: Any?) -> Result<BridgeRequest, BridgeError> {
        guard let dict = body as? [String: Any],
              let id = dict["id"] as? String, !id.isEmpty, id.count <= 128,
              let type = dict["type"] as? String, !type.isEmpty, type.count <= 64
        else { return .failure(.badMessage) }
        if let payload = dict["payload"], !(payload is [String: Any]), !(payload is NSNull) {
            return .failure(.badMessage)
        }
        return .success(BridgeRequest(id: id, type: type, payload: dict["payload"] as? [String: Any] ?? [:]))
    }
}

public enum BridgeCommand: Equatable {
    case windowShow, windowHide, windowToggle
    case windowSetPinned(Bool)
    case notify(title: String, body: String)
    case linkOpen(URL)
    case fileReveal(URL)
    case appInfo, stackStatus, launchAtLoginGet
    case launchAtLoginSet(Bool)
    case notImplemented(String)

    /// Voice is S4; these reply with a not_implemented error until then.
    public static let stubbedTypes: Set<String> = ["mic.start", "mic.stop", "tts.speak", "tts.stop"]

    public static func from(_ request: BridgeRequest, home: String, fileExists: (String) -> Bool)
        -> Result<BridgeCommand, BridgeError>
    {
        let p = request.payload
        switch request.type {
        case "window.show", "window.open": return .success(.windowShow)
        case "window.hide": return .success(.windowHide)
        case "window.toggle": return .success(.windowToggle)
        case "window.setPinned":
            guard let pinned = strictBool(p["pinned"]) else { return .failure(.invalidPayload("pinned must be a boolean")) }
            return .success(.windowSetPinned(pinned))
        case "notify":
            guard let title = p["title"] as? String, !title.isEmpty, title.count <= 200 else {
                return .failure(.invalidPayload("title must be a non-empty string (≤200)"))
            }
            let body = p["body"] as? String ?? ""
            guard body.count <= 1000 else { return .failure(.invalidPayload("body too long (≤1000)")) }
            return .success(.notify(title: title, body: body))
        case "link.open":
            guard let raw = p["url"] as? String, let url = BridgeLinks.validate(raw) else {
                return .failure(.invalidPayload("url must be an http(s) URL with a host"))
            }
            return .success(.linkOpen(url))
        case "file.reveal":
            guard let raw = p["path"] as? String,
                  let url = BridgeFiles.validateReveal(raw, home: home, fileExists: fileExists)
            else { return .failure(.invalidPayload("path must be an existing absolute path under the home folder")) }
            return .success(.fileReveal(url))
        case "app.info": return .success(.appInfo)
        case "stack.status": return .success(.stackStatus)
        case "launchAtLogin.get": return .success(.launchAtLoginGet)
        case "launchAtLogin.set":
            guard let enabled = strictBool(p["enabled"]) else { return .failure(.invalidPayload("enabled must be a boolean")) }
            return .success(.launchAtLoginSet(enabled))
        default:
            if stubbedTypes.contains(request.type) { return .success(.notImplemented(request.type)) }
            return .failure(.unknownType(request.type))
        }
    }

    public var name: String {
        switch self {
        case .windowShow: return "window.show"
        case .windowHide: return "window.hide"
        case .windowToggle: return "window.toggle"
        case .windowSetPinned: return "window.setPinned"
        case .notify: return "notify"
        case .linkOpen: return "link.open"
        case .fileReveal: return "file.reveal"
        case .appInfo: return "app.info"
        case .stackStatus: return "stack.status"
        case .launchAtLoginGet: return "launchAtLogin.get"
        case .launchAtLoginSet: return "launchAtLogin.set"
        case .notImplemented(let type): return type
        }
    }
}

/// A real JS boolean only (WebKit passes booleans as CFBoolean NSNumbers; 0/1 numbers are rejected).
public func strictBool(_ value: Any?) -> Bool? {
    guard let number = value as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID() else { return nil }
    return number.boolValue
}

public enum BridgeLinks {
    public static func validate(_ raw: String) -> URL? {
        guard raw.count <= 4096, let c = URLComponents(string: raw),
              let scheme = c.scheme?.lowercased(), scheme == "http" || scheme == "https",
              let host = c.host, !host.isEmpty, c.user == nil, c.password == nil
        else { return nil }
        return c.url
    }
}

public enum BridgeFiles {
    public static func validateReveal(_ raw: String, home: String, fileExists: (String) -> Bool) -> URL? {
        guard raw.hasPrefix("/"), !home.isEmpty else { return nil }
        let path = URL(fileURLWithPath: raw).standardizedFileURL.resolvingSymlinksInPath().path
        let root = URL(fileURLWithPath: home).standardizedFileURL.resolvingSymlinksInPath().path
        guard path.hasPrefix(root + "/"), fileExists(path) else { return nil }
        return URL(fileURLWithPath: path)
    }
}

public enum BridgeScript {
    public static let handlerName = "jaeger"
    public static let eventName = "jaeger:native"

    /// JS that dispatches `jaeger:native` with `detail` (nil if detail is not JSON-serialisable).
    public static func event(_ detail: [String: Any]) -> String? {
        guard JSONSerialization.isValidJSONObject(detail),
              let data = try? JSONSerialization.data(withJSONObject: detail, options: [.sortedKeys]),
              var json = String(data: data, encoding: .utf8)
        else { return nil }
        json = json.replacingOccurrences(of: "\u{2028}", with: "\\u2028")
            .replacingOccurrences(of: "\u{2029}", with: "\\u2029")
        return "window.dispatchEvent(new CustomEvent(\"\(eventName)\",{detail:\(json)}));"
    }

    /// Document-start, main-frame-only user script: host marker + promise API.
    public static let userScript = """
        (function () {
          if (window.jaegerNative) { return; }
          try { document.documentElement.setAttribute('data-jaeger-host', 'macos'); } catch (e) {}
          var pending = {};
          var seq = 0;
          window.addEventListener('jaeger:native', function (e) {
            var d = e.detail || {};
            if (d.type !== 'reply' || !pending[d.id]) { return; }
            var p = pending[d.id];
            delete pending[d.id];
            if (d.ok) { p.resolve(d.result); } else { p.reject(new Error(d.error || 'error')); }
          });
          window.jaegerNative = Object.freeze({
            version: 1,
            post: function (type, payload) {
              return new Promise(function (resolve, reject) {
                var id = 'j' + (++seq) + '-' + Date.now();
                pending[id] = { resolve: resolve, reject: reject };
                try {
                  window.webkit.messageHandlers.jaeger.postMessage({ id: id, type: type, payload: payload || {} });
                } catch (err) { delete pending[id]; reject(err); }
              });
            }
          });
        })();
        """
}

/// Origin rule for StudioWindowChrome's `aetherWindow` handler (same rule as the `jaeger` bridge;
/// fails closed when no origin is configured).
public enum WindowChromePolicy {
    public static func accepts(_ frame: BridgeFrame, allowed: LoopbackOrigin?) -> Bool {
        guard let allowed else { return false }
        return BridgeOriginPolicy.accepts(frame, allowed: allowed)
    }
}
