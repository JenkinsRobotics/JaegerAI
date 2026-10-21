// JaegerShellCore: the `jaeger` JS⇄native bridge contract (pure, unit-tested).
//
// JS→native: window.webkit.messageHandlers.jaeger.postMessage({id, type, payload}),
// normally through window.jaegerNative.post(type, payload) → Promise (user script below).
// native→JS: window.dispatchEvent(new CustomEvent("jaeger:native", {detail})), including
// {type:"reply", id, ok, result|error}.
// Messages are accepted only from the main frame of the effective loopback WebUI origin.
// No eval, no arbitrary command execution, no file contents. stack.start/stop run only the fixed stack
// actions of StackController (dev: own child processes; production: confirm sheet first).
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
    case notificationStatus, notificationNavigation
    case notificationNavigationAck(String)
    case notificationBadge(ActivityBadgeState)
    case notify(title: String, body: String, sessionId: String?)
    case linkOpen(URL)
    case fileReveal(URL)
    case appInfo, stackStatus, launchAtLoginGet
    case stackStart, stackStop
    case launchAtLoginSet(Bool)
    case voiceStatus
    case micStart(mode: String)
    case micStop
    case ttsSpeak(text: String, voice: String?)
    case ttsStop
    // jaeger_ai/interfaces/ui NativeHost (chat/nativeHost.ts, platform/native.ts)
    case openExternal(URL)
    case openFile(URL)
    case clipboardWrite(String)
    case micStatus, ttsStatus
    case filesPick(FilePickOptions)
    case notImplemented(String)

    /// Types that are routed but not implemented yet (none since S4 voice).
    public static let stubbedTypes: Set<String> = []
    public static let micModes: Set<String> = ["dictation", "push-to-talk"]

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
        case "notifications.status": return .success(.notificationStatus)
        case "notifications.badge":
            guard let raw = p["state"] as? String, let state = ActivityBadgeState(rawValue: raw) else {
                return .failure(.invalidPayload("badge state must be off, present, absent or unknown"))
            }
            return .success(.notificationBadge(state))
        case "notifications.navigation": return .success(.notificationNavigation)
        case "notifications.navigationAck":
            guard let id = p["id"] as? String, id.count == 36, UUID(uuidString: id) != nil else {
                return .failure(.invalidPayload("valid notification navigation identity required"))
            }
            return .success(.notificationNavigationAck(id))
        case "notify":
            guard let title = p["title"] as? String, !title.isEmpty, title.count <= 200 else {
                return .failure(.invalidPayload("title must be a non-empty string (≤200)"))
            }
            let body = p["body"] as? String ?? ""
            guard body.count <= 1000 else { return .failure(.invalidPayload("body too long (≤1000)")) }
            var sessionId: String?
            if let raw = p["session_id"] {
                guard let id = raw as? String, NotificationDestination.validSession(id) else {
                    return .failure(.invalidPayload("session_id must be a bounded conversation identity, not a URL"))
                }
                sessionId = id
            }
            return .success(.notify(title: title, body: body, sessionId: sessionId))
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
        case "stack.start": return .success(.stackStart)
        case "stack.stop": return .success(.stackStop)
        case "launchAtLogin.get": return .success(.launchAtLoginGet)
        case "launchAtLogin.set":
            guard let enabled = strictBool(p["enabled"]) else { return .failure(.invalidPayload("enabled must be a boolean")) }
            return .success(.launchAtLoginSet(enabled))
        case "voice.status": return .success(.voiceStatus)
        case "mic.start":
            if let raw = p["mode"], !(raw is String) { return .failure(.invalidPayload("mode must be a string")) }
            let mode = p["mode"] as? String ?? "dictation"
            guard micModes.contains(mode) else { return .failure(.invalidPayload("mode must be dictation or push-to-talk")) }
            return .success(.micStart(mode: mode))
        case "mic.stop": return .success(.micStop)
        case "tts.speak":
            guard let text = p["text"] as? String, !text.isEmpty, text.count <= 10000 else {
                return .failure(.invalidPayload("text must be a non-empty string (≤10000)"))
            }
            guard !TTSText.plainForSpeech(text).isEmpty else { return .failure(.invalidPayload("nothing to speak")) }
            if let raw = p["voice"], !(raw is String) { return .failure(.invalidPayload("voice must be a string")) }
            let voice = p["voice"] as? String
            if let voice, voice.count > 128 { return .failure(.invalidPayload("voice too long")) }
            return .success(.ttsSpeak(text: text, voice: voice))
        case "tts.stop": return .success(.ttsStop)
        case "open.external":
            guard let raw = p["url"] as? String, let url = BridgeLinks.validate(raw) else {
                return .failure(.invalidPayload("url must be an http(s) URL with a host"))
            }
            return .success(.openExternal(url))
        case "open.file":
            guard let raw = p["path"] as? String,
                  let url = BridgeFiles.validateReveal(raw, home: home, fileExists: fileExists)
            else { return .failure(.invalidPayload("path must be an existing absolute path under the home folder")) }
            return .success(.openFile(url))
        case "clipboard.write":
            guard let text = p["text"] as? String, text.count <= 1_000_000 else {
                return .failure(.invalidPayload("text must be a string (≤1,000,000)"))
            }
            return .success(.clipboardWrite(text))
        case "mic.status": return .success(.micStatus)
        case "tts.status": return .success(.ttsStatus)
        case "files.pick": return FilePickOptions.parse(p).map { .filesPick($0) }
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
        case .notificationStatus: return "notifications.status"
        case .notificationNavigation: return "notifications.navigation"
        case .notificationNavigationAck: return "notifications.navigationAck"
        case .notificationBadge: return "notifications.badge"
        case .notify: return "notify"
        case .linkOpen: return "link.open"
        case .fileReveal: return "file.reveal"
        case .appInfo: return "app.info"
        case .stackStatus: return "stack.status"
        case .stackStart: return "stack.start"
        case .stackStop: return "stack.stop"
        case .launchAtLoginGet: return "launchAtLogin.get"
        case .launchAtLoginSet: return "launchAtLogin.set"
        case .voiceStatus: return "voice.status"
        case .micStart: return "mic.start"
        case .micStop: return "mic.stop"
        case .ttsSpeak: return "tts.speak"
        case .ttsStop: return "tts.stop"
        case .openExternal: return "open.external"
        case .openFile: return "open.file"
        case .clipboardWrite: return "clipboard.write"
        case .micStatus: return "mic.status"
        case .ttsStatus: return "tts.status"
        case .filesPick: return "files.pick"
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

/// What the new main screen (jaeger_ai/interfaces/ui, 2026-10-17) expects from window.jaegerNative:
/// src/chat/nativeHost.ts (open.external, open.file, clipboard.write, appearance.changed) and
/// src/platform/native.ts (probeVoice: mic.status + tts.status must not be not_implemented;
/// events window.visibility, hotkey). `post(type, payload) => Promise<result>`; errors reject.
public enum HostContract {
    public static let requestTypes = ["open.external", "open.file", "clipboard.write", "mic.status", "tts.status"]
    public static let eventTypes = ["window.visibility", "hotkey", "appearance.changed"]
}

// MARK: files.pick — the composer's + on the macOS host (IDE Chat H8 contract: JaegerChatHost.pickFiles).
// The page asks; the shell shows NSOpenPanel; only what the user picked comes back, filtered by these
// options: {path, name, size, mimeType, uri file://}. [] on cancel. Paths go only to the loopback page.

public struct FilePickOptions: Equatable, Sendable {
    public static let maxFilesCap = 32
    public var multiple: Bool
    public var maxFiles: Int
    public var maxBytes: Int?
    /// MIME types (`image/png`, `image/*`) or extensions (`.pdf`), lowercased. Empty: anything.
    public var accept: [String]

    /// The open panel's caption, e.g. "Up to 8 files, 20 MB each". Binary units, so the UI's
    /// 20 * 1024 * 1024 limit reads "20 MB" (decimal would say "21 MB").
    public var panelMessage: String {
        guard let maxBytes else { return "" }
        let size = ByteCountFormatter.string(fromByteCount: Int64(maxBytes), countStyle: .binary)
        return "Up to \(maxFiles) file\(maxFiles == 1 ? "" : "s"), \(size) each"
    }

    public init(multiple: Bool = false, maxFiles: Int? = nil, maxBytes: Int? = nil, accept: [String] = []) {
        self.multiple = multiple
        self.maxFiles = multiple ? min(maxFiles ?? Self.maxFilesCap, Self.maxFilesCap) : 1
        self.maxBytes = maxBytes
        self.accept = accept
    }

    public static func parse(_ p: [String: Any]) -> Result<FilePickOptions, BridgeError> {
        var multiple = false
        if let raw = p["multiple"] {
            guard let value = strictBool(raw) else { return .failure(.invalidPayload("multiple must be a boolean")) }
            multiple = value
        }
        func positiveInt(_ key: String) -> Result<Int?, BridgeError> {
            guard let raw = p[key] else { return .success(nil) }
            guard let number = raw as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
                  number.doubleValue == number.doubleValue.rounded(), number.doubleValue >= 1, number.doubleValue <= 1e15
            else { return .failure(.invalidPayload("\(key) must be a positive integer")) }
            return .success(number.intValue)
        }
        let maxFiles: Int?, maxBytes: Int?
        switch positiveInt("maxFiles") { case .failure(let e): return .failure(e); case .success(let v): maxFiles = v }
        switch positiveInt("maxBytes") { case .failure(let e): return .failure(e); case .success(let v): maxBytes = v }
        var accept: [String] = []
        if let raw = p["accept"] {
            guard let list = raw as? [Any], list.count <= 64,
                  let items = list as? [String], items.allSatisfy({ !$0.isEmpty && $0.count <= 128 })
            else { return .failure(.invalidPayload("accept must be a list of MIME types or .ext (≤64)")) }
            accept = items.map { $0.trimmingCharacters(in: .whitespaces).lowercased() }
        }
        return .success(FilePickOptions(multiple: multiple, maxFiles: maxFiles, maxBytes: maxBytes, accept: accept))
    }

    /// Whether a file passes `accept` (by extension or MIME, `type/*` wildcards).
    public func accepts(name: String, mimeType: String) -> Bool {
        if accept.isEmpty { return true }
        let ext = (name as NSString).pathExtension.lowercased()
        let mime = mimeType.lowercased()
        return accept.contains { rule in
            if rule.hasPrefix(".") { return !ext.isEmpty && rule == ".\(ext)" }
            if rule.hasSuffix("/*") { return mime.hasPrefix(String(rule.dropLast(1))) }
            return rule == mime
        }
    }
}

public struct PickedFile: Equatable, Sendable {
    public let path: String
    public let name: String
    public let size: Int
    public let mimeType: String
    public let isRegularFile: Bool
    public init(path: String, name: String, size: Int, mimeType: String, isRegularFile: Bool = true) {
        self.path = path; self.name = name; self.size = size; self.mimeType = mimeType; self.isRegularFile = isRegularFile
    }

    /// The H8 ChatAttachment shape the page receives.
    public var reply: [String: Any] {
        ["path": path, "name": name, "size": size, "mimeType": mimeType, "uri": URL(fileURLWithPath: path).absoluteString]
    }
}

public enum FilePick {
    /// Regular files only; drops what `accept` or `maxBytes` refuse, then keeps the first `maxFiles`.
    public static func select(_ picked: [PickedFile], _ options: FilePickOptions) -> [PickedFile] {
        let kept = picked.filter { file in
            file.isRegularFile && file.path.hasPrefix("/") && options.accepts(name: file.name, mimeType: file.mimeType)
                && (options.maxBytes.map { file.size <= $0 } ?? true)
        }
        return Array(kept.prefix(options.maxFiles))
    }
}
