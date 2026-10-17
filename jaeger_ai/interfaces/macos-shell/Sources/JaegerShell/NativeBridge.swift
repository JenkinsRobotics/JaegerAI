// NativeBridge.swift — the `jaeger` script-message handler (Jaeger original, not derived from AetherStudio).
// Contract and validation live in JaegerShellCore/Bridge.swift. StudioWindowChrome's `aetherWindow`
// handler is separate and unchanged.

import AppKit
import JaegerShellCore
import ServiceManagement
import UserNotifications
import WebKit

protocol BridgeHost: AnyObject {
    func bridgeShowWindow()
    func bridgeHideWindow()
    func bridgeToggleWindow()
    func bridgeSetPinned(_ pinned: Bool)
    func bridgeNotify(title: String, body: String)
    func bridgeOpenLink(_ url: URL)
    func bridgeReveal(_ url: URL)
    func bridgeAppInfo() -> [String: Any]
    func bridgeStackStatus(_ done: @escaping ([String: Any]) -> Void)
    func bridgeLoginItemStatus() -> String
    func bridgeSetLoginItem(_ enabled: Bool) throws -> String
    func bridgeVoiceStatus() -> [String: Any]
    func bridgeMicStart(mode: String, done: @escaping BridgeDone)
    func bridgeMicStop(done: @escaping BridgeDone)
    func bridgeTTSSpeak(text: String, voice: String?, done: @escaping BridgeDone)
    func bridgeTTSStop()
}

/// Breaks the WKUserContentController → handler retain cycle.
private final class WeakMessageHandler: NSObject, WKScriptMessageHandler {
    weak var target: WKScriptMessageHandler?
    init(_ target: WKScriptMessageHandler) { self.target = target }
    func userContentController(_ c: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.userContentController(c, didReceive: message)
    }
}

final class NativeBridge: NSObject, WKScriptMessageHandler {
    let allowed: LoopbackOrigin
    let label: String
    weak var host: BridgeHost?
    weak var webView: WKWebView?
    private(set) var accepted = 0
    private(set) var rejections: [String] = []

    init(allowed: LoopbackOrigin, host: BridgeHost, label: String) {
        self.allowed = allowed
        self.host = host
        self.label = label
    }

    func install(in configuration: WKWebViewConfiguration) {
        let controller = configuration.userContentController
        controller.addUserScript(WKUserScript(
            source: BridgeScript.userScript, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        controller.add(WeakMessageHandler(self), name: BridgeScript.handlerName)
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        let info = message.frameInfo
        let origin = info.securityOrigin
        let frame = BridgeFrame(isMainFrame: info.isMainFrame, scheme: origin.protocol, host: origin.host, port: origin.port)
        let type = (message.body as? [String: Any])?["type"] as? String ?? "?"
        guard message.name == BridgeScript.handlerName, BridgeOriginPolicy.accepts(frame, allowed: allowed) else {
            let detail = "\(frame.description) type=\(type.prefix(64))"
            rejections.append(detail)
            shellLog("[shell][bridge] rejected \(detail) (\(label))")
            return
        }
        accepted += 1
        let request: BridgeRequest
        switch BridgeRequest.parse(message.body) {
        case .failure(let error):
            shellLog("[shell][bridge] \(error.message) (\(label))")
            if let id = (message.body as? [String: Any])?["id"] as? String { replyError(id, error.message) }
            return
        case .success(let parsed): request = parsed
        }
        switch BridgeCommand.from(request, home: NSHomeDirectory(), fileExists: { FileManager.default.fileExists(atPath: $0) }) {
        case .failure(let error):
            shellLog("[shell][bridge] \(request.type) refused: \(error.message) (\(label))")
            replyError(request.id, error.message)
        case .success(let command):
            perform(command, id: request.id)
        }
    }

    private func perform(_ command: BridgeCommand, id: String) {
        guard let host else { replyError(id, "no_host"); return }
        shellLog("[shell][bridge] \(command.name) (\(label))")
        switch command {
        case .windowShow: host.bridgeShowWindow(); reply(id, ["visible": true])
        case .windowHide: host.bridgeHideWindow(); reply(id, ["visible": false])
        case .windowToggle: host.bridgeToggleWindow(); reply(id, [:])
        case .windowSetPinned(let pinned): host.bridgeSetPinned(pinned); reply(id, ["pinned": pinned])
        case .notify(let title, let body): host.bridgeNotify(title: title, body: body); reply(id, ["queued": true])
        case .linkOpen(let url): host.bridgeOpenLink(url); reply(id, ["opened": url.absoluteString])
        case .fileReveal(let url): host.bridgeReveal(url); reply(id, ["revealed": url.path])
        case .appInfo: reply(id, host.bridgeAppInfo())
        case .stackStatus: host.bridgeStackStatus { [weak self] result in self?.reply(id, result) }
        case .launchAtLoginGet: reply(id, ["status": host.bridgeLoginItemStatus()])
        case .launchAtLoginSet(let enabled):
            do { reply(id, ["status": try host.bridgeSetLoginItem(enabled)]) } catch {
                replyError(id, "launch_at_login_failed: \(error.localizedDescription)")
            }
        case .voiceStatus: reply(id, host.bridgeVoiceStatus())
        case .micStart(let mode): host.bridgeMicStart(mode: mode) { [weak self] r, e in self?.finish(id, r, e) }
        case .micStop: host.bridgeMicStop { [weak self] r, e in self?.finish(id, r, e) }
        case .ttsSpeak(let text, let voice): host.bridgeTTSSpeak(text: text, voice: voice) { [weak self] r, e in self?.finish(id, r, e) }
        case .ttsStop: host.bridgeTTSStop(); reply(id, ["stopped": true])
        case .notImplemented(let type): replyError(id, "not_implemented: \(type)")
        }
    }

    private func finish(_ id: String, _ result: [String: Any]?, _ error: String?) {
        if let error { replyError(id, error) } else { reply(id, result ?? [:]) }
    }

    func reply(_ id: String, _ result: [String: Any]) { send(["type": "reply", "id": id, "ok": true, "result": result]) }
    func replyError(_ id: String, _ error: String) { send(["type": "reply", "id": id, "ok": false, "error": error]) }

    /// native→JS event; only delivered while the page is on the allowed loopback origin.
    func send(_ detail: [String: Any]) {
        guard let webView, let url = webView.url, url.scheme == "http",
              NavigationPolicy.decide(url, allowed: allowed) == .allow
        else {
            shellLog("[shell][bridge] event \(detail["type"] ?? "?") dropped: page not on \(allowed.string) (\(label))")
            return
        }
        guard let js = BridgeScript.event(detail) else { return }
        webView.evaluateJavaScript(js, completionHandler: nil)
    }
}

extension ShellEnvironment {
    static func appInfo(_ start: StartURL.Resolution) -> [String: Any] {
        let info = Bundle.main.infoDictionary ?? [:]
        return [
            "bundle_id": Bundle.main.bundleIdentifier ?? "",
            "version": info["CFBundleShortVersionString"] as? String ?? "",
            "build": info["CFBundleVersion"] as? String ?? "",
            "dev_build": isDevBuild,
            "host": "macos",
            "origin": start.origin.string,
            "bridge_version": 1,
        ]
    }

    static func probe(_ urlString: String, _ done: @escaping (String) -> Void) {
        guard let url = URL(string: urlString) else { done("invalid"); return }
        let request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 1.5)
        URLSession(configuration: .ephemeral).dataTask(with: request) { _, response, _ in
            let code = (response as? HTTPURLResponse)?.statusCode
            let text = code.map { (200..<400).contains($0) ? "running" : "http_\($0)" } ?? "not_running"
            DispatchQueue.main.async { done(text) }
        }.resume()
    }

    /// Read-only probes of the loopback WebUI and gateway (same as the status menu).
    static func stackStatus(_ start: StartURL.Resolution, _ done: @escaping ([String: Any]) -> Void) {
        var result: [String: Any] = ["webui_origin": start.origin.string, "gateway_origin": gateway().origin.string]
        let group = DispatchGroup()
        group.enter(); probe(start.origin.string + "/") { result["webui"] = $0; group.leave() }
        group.enter(); probe(gateway().origin.string + "/health") { result["gateway"] = $0; group.leave() }
        group.notify(queue: .main) { done(result) }
    }
}

extension JaegerShellApplication: BridgeHost {
    func bridgeShowWindow() { showWindow() }
    func bridgeHideWindow() { hideWindow() }
    func bridgeToggleWindow() { toggleWindow() }
    func bridgeSetPinned(_ pinned: Bool) { mainWindow?.level = pinned ? .floating : .normal }
    func bridgeOpenLink(_ url: URL) { NSWorkspace.shared.open(url) }
    func bridgeReveal(_ url: URL) { NSWorkspace.shared.activateFileViewerSelecting([url]) }
    func bridgeAppInfo() -> [String: Any] { ShellEnvironment.appInfo(start) }
    func bridgeStackStatus(_ done: @escaping ([String: Any]) -> Void) { ShellEnvironment.stackStatus(start, done) }
    func bridgeLoginItemStatus() -> String { ShellEnvironment.loginItemStatus() }

    func bridgeSetLoginItem(_ enabled: Bool) throws -> String {
        let status = try ShellEnvironment.setLoginItem(enabled)
        shellLog("[shell][login] set enabled=\(enabled) via bridge → \(status)")
        return status
    }

    func bridgeNotify(title: String, body: String) {
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { granted, error in
            guard granted else {
                shellLog("[shell][notify] not authorised \(error?.localizedDescription ?? "")")
                return
            }
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body
            center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
        }
    }
}

extension JaegerShellApplication {
    func bridgeVoiceStatus() -> [String: Any] {
        VoiceController.status(state: voiceController?.state ?? "idle", speaking: voiceController?.tts.isSpeaking ?? false)
    }
    func bridgeMicStart(mode: String, done: @escaping BridgeDone) { voice().micStart(mode: mode, done: done) }
    func bridgeMicStop(done: @escaping BridgeDone) { voice().micStop(done: done) }
    func bridgeTTSSpeak(text: String, voice choice: String?, done: @escaping BridgeDone) {
        voice().speak(text: text, voice: choice, done: done)
    }
    func bridgeTTSStop() { voiceController?.stopSpeaking() }
}
