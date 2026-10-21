// NativeBridge.swift — the `jaeger` script-message handler (Jaeger original, not derived from AetherStudio).
// Contract and validation live in JaegerShellCore/Bridge.swift. StudioWindowChrome's `aetherWindow`
// handler is separate and unchanged.

import AppKit
import ApplicationServices
import CoreGraphics
import JaegerShellCore
import ServiceManagement
import UniformTypeIdentifiers
import UserNotifications
import WebKit

protocol BridgeHost: AnyObject {
    func bridgeShowWindow()
    func bridgeHideWindow()
    func bridgeToggleWindow()
    func bridgeSetPinned(_ pinned: Bool)
    func bridgeNotificationStatus(_ done: @escaping ([String: Any]) -> Void)
    func bridgeNotify(title: String, body: String, sessionId: String?, done: @escaping BridgeDone)
    func bridgeActivityBadge(_ state: ActivityBadgeState) -> [String: Any]
    func bridgeAcknowledgeNotificationNavigation(_ id: String) -> Bool
    func bridgeNotificationNavigation() -> [String: Any]
    func bridgeOpenLink(_ url: URL)
    func bridgeReveal(_ url: URL)
    func bridgeAppInfo() -> [String: Any]
    func bridgeStackStatus(_ done: @escaping ([String: Any]) -> Void)
    func bridgeStackStart(done: @escaping BridgeDone)
    func bridgeStackStop(done: @escaping BridgeDone)
    func bridgeLoginItemStatus() -> String
    func bridgeSetLoginItem(_ enabled: Bool) throws -> String
    func bridgeVoiceStatus() -> [String: Any]
    func bridgeMicStart(mode: String, done: @escaping BridgeDone)
    func bridgeMicStop(done: @escaping BridgeDone)
    func bridgeTTSSpeak(text: String, voice: String?, done: @escaping BridgeDone)
    func bridgeTTSStop()
    func bridgeOpenFile(_ url: URL)
    func bridgeComputerStatus() -> [String: Any]
    func bridgeComputerSettings(_ target: ComputerSettingsTarget) -> Bool
    func bridgeReadClipboard() -> [String: Any]
    func bridgeCopy(_ text: String) -> Bool?
    func bridgeMicStatus() -> [String: Any]
    func bridgeTTSStatus() -> [String: Any]
    func bridgePickFiles(_ options: FilePickOptions, done: @escaping BridgeDone)
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
        case .notificationStatus: host.bridgeNotificationStatus { [weak self] result in self?.reply(id, result) }
        case .notificationBadge(let state): reply(id, host.bridgeActivityBadge(state))
        case .notificationNavigation: reply(id, host.bridgeNotificationNavigation())
        case .notificationNavigationAck(let navigationId): reply(id, ["cleared": host.bridgeAcknowledgeNotificationNavigation(navigationId)])
        case .notify(let title, let body, let sessionId): host.bridgeNotify(title: title, body: body, sessionId: sessionId) { [weak self] result, error in self?.finish(id, result, error) }
        case .linkOpen(let url): host.bridgeOpenLink(url); reply(id, ["opened": url.absoluteString])
        case .fileReveal(let url): host.bridgeReveal(url); reply(id, ["revealed": url.path])
        case .appInfo: reply(id, host.bridgeAppInfo())
        case .stackStatus: host.bridgeStackStatus { [weak self] result in self?.reply(id, result) }
        case .stackStart: host.bridgeStackStart { [weak self] r, e in self?.finish(id, r, e) }
        case .stackStop: host.bridgeStackStop { [weak self] r, e in self?.finish(id, r, e) }
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
        case .openExternal(let url): host.bridgeOpenLink(url); reply(id, ["opened": url.absoluteString])
        case .openFile(let url): host.bridgeOpenFile(url); reply(id, ["opened": url.path])
        case .computerStatus: reply(id, host.bridgeComputerStatus())
        case .computerSettings(let target): reply(id, ["open_request_accepted": host.bridgeComputerSettings(target), "permission_changed": false])
        case .clipboardRead: reply(id, host.bridgeReadClipboard())
        case .clipboardWrite(let text):
            if let copied = host.bridgeCopy(text) {
                if copied { reply(id, ["copied": true]) }
                else { replyError(id, "clipboard_write_failed") }
            } else { reply(id, ["copied": false, "recorded": true]) }
        case .micStatus: reply(id, host.bridgeMicStatus())
        case .ttsStatus: reply(id, host.bridgeTTSStatus())
        case .filesPick(let options): host.bridgePickFiles(options) { [weak self] result, error in self?.finish(id, result, error) }
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
        var result: [String: Any] = ["main_screen_origin": start.origin.string, "gateway_origin": gateway().origin.string]
        let group = DispatchGroup()
        group.enter(); probe(start.origin.string + "/") { result["main_screen"] = $0; group.leave() }
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
    func bridgeStackStatus(_ done: @escaping ([String: Any]) -> Void) { stack.status(done) }
    func bridgeStackStart(done: @escaping BridgeDone) { stack.fromBridge(.start, done: done) }
    func bridgeStackStop(done: @escaping BridgeDone) { stack.fromBridge(.stop, done: done) }
    func bridgeLoginItemStatus() -> String { ShellEnvironment.loginItemStatus() }

    func bridgeSetLoginItem(_ enabled: Bool) throws -> String {
        let status = try ShellEnvironment.setLoginItem(enabled)
        shellLog("[shell][login] set enabled=\(enabled) via bridge → \(status)")
        return status
    }

    func bridgeActivityBadge(_ state: ActivityBadgeState) -> [String: Any] {
        statusController?.setActivityBadge(state)
        return ["applied": statusController?.isPresent == true, "state": state.rawValue,
                "scope": "menu_bar_retained_activity_presence", "dock_badge_available": false]
    }

    func bridgeAcknowledgeNotificationNavigation(_ id: String) -> Bool {
        notificationNavigation.acknowledge(id)
    }

    func bridgeNotificationNavigation() -> [String: Any] {
        let navigation = notificationNavigation.payload
        if let navigation { return ["navigation": navigation] }
        return ["navigation": NSNull()]
    }

    func bridgeNotificationStatus(_ done: @escaping ([String: Any]) -> Void) {
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            let status: String
            switch settings.authorizationStatus {
            case .authorized: status = "authorized"
            case .provisional: status = "provisional"
            case .denied: status = "denied"
            case .notDetermined: status = "not_determined"
            @unknown default: status = "unknown"
            }
            DispatchQueue.main.async { done(["authorization": status, "permission_requested": false, "delivery_proven": false, "activity_badge_available": self.statusController?.isPresent == true, "activity_badge_scope": "menu_bar_retained_activity_presence", "activity_badge_state": self.statusController?.activityBadgeState ?? "off", "dock_badge_available": false]) }
        }
    }

    func bridgeNotify(title: String, body: String, sessionId: String?, done: @escaping BridgeDone) {
        let center = UNUserNotificationCenter.current()
        center.getNotificationSettings { settings in
            guard [.authorized, .provisional].contains(settings.authorizationStatus) else {
                DispatchQueue.main.async { done(nil, "notifications_not_authorized_no_permission_requested") }
                return
            }
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body
            content.userInfo = (sessionId.map(NotificationDestination.conversation) ?? .inbox).payload
            let identifier = UUID().uuidString
            center.add(UNNotificationRequest(identifier: identifier, content: content, trigger: nil)) { error in
                DispatchQueue.main.async {
                    if error != nil { done(nil, "notification_submission_failed") }
                    else { done(["accepted": true, "notification_id": identifier, "delivery_proven": false, "permission_requested": false], nil) }
                }
            }
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
    func bridgeOpenFile(_ url: URL) { NSWorkspace.shared.open(url) }
    func bridgeComputerStatus() -> [String: Any] {
        ["scope": "native_shell_process", "process_id": ProcessInfo.processInfo.processIdentifier,
         "screen_os_permission": CGPreflightScreenCaptureAccess() ? "granted" : "not_granted_or_undetermined",
         "input_os_permission": AXIsProcessTrusted() ? "granted" : "not_granted_or_undetermined",
         "permission_requested": false, "capture_performed": false, "input_performed": false,
         "automation_permission": "per_target_unknown", "tool_authority": "not_inferred"]
    }
    func bridgeComputerSettings(_ target: ComputerSettingsTarget) -> Bool {
        NSWorkspace.shared.open(target.url)
    }
    func bridgeReadClipboard() -> [String: Any] {
        // No polling, log, transcript or model admission. Explicit trusted UI request only.
        ClipboardPreview.project(NSPasteboard.general.string(forType: .string))
    }
    func bridgeCopy(_ text: String) -> Bool? {
        NSPasteboard.general.clearContents()
        return NSPasteboard.general.setString(text, forType: .string)
    }
    func bridgeMicStatus() -> [String: Any] { VoiceController.micStatus(recording: voiceController?.isRecording ?? false) }
    func bridgeTTSStatus() -> [String: Any] { VoiceController.ttsStatus(speaking: voiceController?.tts.isSpeaking ?? false) }
}

// MARK: files.pick — NSOpenPanel for the composer's +. Only what the user picks is returned.
extension JaegerShellApplication {
    func bridgePickFiles(_ options: FilePickOptions, done: @escaping BridgeDone) {
        guard !filePanelOpen else { done(nil, "picker_busy"); return }
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.resolvesAliases = true
        panel.allowsMultipleSelection = options.multiple
        panel.prompt = "Attach"
        panel.message = options.panelMessage
        let types = FilePickPanel.contentTypes(options.accept)
        if !types.isEmpty { panel.allowedContentTypes = types }
        filePanelOpen = true
        let finish: (NSApplication.ModalResponse) -> Void = { [weak self] response in
            self?.filePanelOpen = false
            guard response == .OK else { done(["files": []], nil); return }
            let picked = panel.urls.map(FilePickPanel.describe)
            let kept = FilePick.select(picked, options)
            shellLog("[shell][files] picked \(picked.count), returned \(kept.count)")
            done(["files": kept.map(\.reply), "dropped": picked.count - kept.count], nil)
        }
        if let window = mainWindow, window.isVisible { panel.beginSheetModal(for: window, completionHandler: finish) }
        else { panel.begin(completionHandler: finish) }
    }
}

enum FilePickPanel {
    /// `accept` → panel types; any rule that has no type leaves the panel open to everything (the
    /// result is still filtered by FilePick.select).
    static func contentTypes(_ accept: [String]) -> [UTType] {
        var types: [UTType] = []
        for rule in accept {
            let type: UTType?
            if rule.hasPrefix(".") { type = UTType(filenameExtension: String(rule.dropFirst())) }
            else if rule.hasSuffix("/*") {
                switch rule {
                case "image/*": type = .image
                case "audio/*": type = .audio
                case "video/*": type = .movie
                case "text/*": type = .text
                default: type = nil
                }
            } else { type = UTType(mimeType: rule) }
            guard let type else { return [] }
            types.append(type)
        }
        return types
    }

    static func describe(_ url: URL) -> PickedFile {
        let resolved = url.resolvingSymlinksInPath()
        let values = try? resolved.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
        let mime = UTType(filenameExtension: resolved.pathExtension)?.preferredMIMEType ?? "application/octet-stream"
        return PickedFile(path: resolved.path, name: resolved.lastPathComponent, size: values?.fileSize ?? 0,
                          mimeType: mime, isRegularFile: values?.isRegularFile ?? false)
    }
}
