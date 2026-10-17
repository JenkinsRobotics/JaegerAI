// Derived from AetherStudio @ ece0209 — Aether CAD/Launcher/AetherCADApplication.swift
// Copyright (c) Jonathan Jenkins and Jenkins Robotics (AetherStudio). Licensed under the Apache License 2.0
// (see LICENSES/AetherStudio-Apache-2.0.txt). Modified for Jaeger by Jenkins Robotics on 2026-10-17:
// renamed; engine spawn (python animacore.httpbridge, .venv, Resources/Web) removed; loads the
// loopback Jaeger WebUI (http://127.0.0.1:8790/?host=macos or the dev override); loopback-only
// navigation + WKContentRuleList; inline "not running" page instead of alert+quit; minimal main
// menu (Quit, Edit, Reload); developer extras only in DEBUG; menu-bar (accessory) app with a
// status item, window hides on close; --verify-launch self-check; global hotkey (JaegerHotkey);
// `jaeger` JS⇄native bridge (NativeBridge) + headless --verify-bridge.

import AppKit
import JaegerShellCore
import ServiceManagement
import WebKit
import os

private let shellLogger = Logger(subsystem: "com.jenkinsrobotics.JaegerAI.uirebuild", category: "shell")

/// Public unified-log line (NSLog arguments are redacted) + stderr.
func shellLog(_ message: String) {
    shellLogger.notice("\(message, privacy: .public)")
    FileHandle.standardError.write(Data((message + "\n").utf8))
}

final class JaegerShellApplication: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate,
    WKUIDelegate, WKDownloadDelegate
{
    private var window: NSWindow?
    private var webView: WKWebView?
    private var loadAttempts = 0
    private var showingErrorPage = false
    private var rulesInstalled = false
    private(set) var statusController: StatusItemController?
    let start: StartURL.Resolution = ShellEnvironment.webUI()
    let verifyMode = CommandLine.arguments.contains("--verify-launch")
    let verifyBridgeMode = CommandLine.arguments.contains("--verify-bridge")
    private(set) var bridge: NativeBridge?
    private var bridgeVerifier: BridgeVerifier?
    var mainWindow: NSWindow? { window }

    func applicationDidFinishLaunching(_ notification: Notification) {
        if let rejected = start.rejected { shellLog("[shell][override] rejected \(rejected)") }
        if let override = start.override { shellLog("[shell][override] accepted \(override)") }
        shellLog("[shell] start_url=\(start.url.absoluteString)")
        if verifyBridgeMode {
            // Headless: no menu, status item, hotkey or visible window.
            let verifier = BridgeVerifier(app: self)
            bridgeVerifier = verifier
            _ = makeWindow()
            installRulesThenLoad()
            verifier.startTimeout()
            return
        }
        installMainMenu()
        statusController = StatusItemController(app: self)
        registerHotkey()
        if verifyMode {
            _ = makeWindow()  // created, never shown, nothing loaded
            emitVerifyReport()
            NSApp.terminate(nil)
            return
        }
        showWindow()
        installRulesThenLoad()
        statusController?.refreshIcon()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false  // menu-bar app: closing the window only hides it
    }

    private lazy var hotkeyChoice = HotkeyConfig.resolve(
        Bundle.main.object(forInfoDictionaryKey: HotkeyConfig.infoPlistKey) as? String)

    private func registerHotkey() {
        if let note = hotkeyChoice.note { shellLog("[shell][hotkey] \(note)") }
        Hotkey.shared.register(hotkeyChoice.spec) { [weak self] in
            shellLog("[shell][hotkey] pressed")
            self?.toggleWindow()
            self?.bridge?.send(["type": "hotkey"])
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        Hotkey.shared.unregister()
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        hideWindow()
        return false
    }

    func hideWindow() {
        window?.orderOut(nil)
        shellLog("[shell] window hidden")
        bridge?.send(["type": "window.visibility", "visible": false])
    }

    private func emitVerifyReport() {
        let info = Bundle.main.infoDictionary ?? [:]
        let lsui = (info["LSUIElement"] as? Bool) == true
        let report: [String: Any] = [
            "ok": lsui && NSApp.activationPolicy() == .accessory && (statusController?.isPresent ?? false)
                && window != nil && start.origin.host == "127.0.0.1",
            "bundle_id": Bundle.main.bundleIdentifier ?? NSNull(),
            "bundle_version": info["CFBundleVersion"] ?? NSNull(),
            "dev_build": ShellEnvironment.isDevBuild,
            "menu_bar_only": lsui && NSApp.activationPolicy() == .accessory,
            "status_item_present": statusController?.isPresent ?? false,
            "window_created": window != nil,
            "window_visible": window?.isVisible ?? false,
            "start_url": start.url.absoluteString,
            "start_url_loopback": start.origin.host == "127.0.0.1",
            "webui_url_override": start.override ?? NSNull(),
            "webui_url_override_rejected": start.rejected ?? NSNull(),
            "gateway_url": ShellEnvironment.gateway().origin.string,
            "login_item_status": ShellEnvironment.loginItemStatus(),
            "launcher": ShellEnvironment.launcherPath() ?? NSNull(),
            "network_requested": false,
            "hotkey": [
                "configured": hotkeyChoice.spec.name,
                "label": hotkeyChoice.spec.label,
                "registered": Hotkey.shared.registered != nil,
                "status": Int(Hotkey.shared.lastStatus),
                "note": hotkeyChoice.note ?? NSNull(),
            ] as [String: Any],
        ]
        if let data = try? JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]) {
            FileHandle.standardOutput.write(data + Data("\n".utf8))
        }
    }

    private let windowChrome = StudioWindowChrome()
    var chrome: StudioWindowChrome { windowChrome }

    func makeWindow() -> NSWindow {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        #if DEBUG
        configuration.preferences.setValue(true, forKey: "developerExtrasEnabled")
        #endif
        windowChrome.allowedOrigin = start.origin
        windowChrome.install(in: configuration)
        let host: BridgeHost = bridgeVerifier ?? self
        let bridge = NativeBridge(allowed: start.origin, host: host, label: "main")
        bridge.install(in: configuration)
        self.bridge = bridge

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsMagnification = false
        self.webView = webView
        bridge.webView = webView

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1024, height: 720),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.title = "Jaeger"
        window.isReleasedWhenClosed = false
        window.delegate = self
        windowChrome.attach(to: window)
        window.setFrameAutosaveName("JaegerShellMainWindow")
        window.contentView = webView
        window.center()
        self.window = window
        return window
    }

    func showWindow() {
        if verifyBridgeMode { return }  // never show a window in the headless check
        let window = self.window ?? makeWindow()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        bridge?.send(["type": "window.visibility", "visible": true])
        if !rulesInstalled && !verifyMode && webView?.url == nil { installRulesThenLoad() }
    }

    func toggleWindow() {
        if let window, window.isVisible, NSApp.isActive, window.isKeyWindow {
            hideWindow()
        } else {
            showWindow()
            shellLog("[shell] window shown")
        }
    }

    private var compiling = false
    private func installRulesThenLoad() {
        guard !compiling, !rulesInstalled else { return }
        compiling = true
        let json = NavigationPolicy.contentRuleListJSON(allowed: start.origin)
        WKContentRuleListStore.default().compileContentRuleList(
            forIdentifier: "jaeger-shell-loopback-\(start.origin.port)", encodedContentRuleList: json
        ) { [weak self] list, error in
            DispatchQueue.main.async {
                guard let self else { return }
                self.compiling = false
                guard let list else {
                    shellLog("[shell] content rule list failed: \(String(describing: error))")
                    self.showErrorPage("The loopback network guard could not be installed.")
                    return
                }
                self.rulesInstalled = true
                self.webView?.configuration.userContentController.add(list)
                shellLog("[shell] loopback rule list installed for \(self.start.origin.string)")
                self.scheduleLoad(after: 0.35)
            }
        }
    }

    private func scheduleLoad(after delay: TimeInterval) {
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self, self.rulesInstalled else { return }
            self.loadAttempts += 1
            self.showingErrorPage = false
            self.webView?.load(URLRequest(url: self.start.url))
        }
    }

    @objc func reloadShell(_ sender: Any?) {
        loadAttempts = 0
        if rulesInstalled { scheduleLoad(after: 0) } else { installRulesThenLoad() }
    }

    private func showErrorPage(_ detail: String) {
        showingErrorPage = true
        let address = start.origin.string
        webView?.loadHTMLString("""
            <body style="font-family:-apple-system,sans-serif;background:#f4f4f5;color:#222;
                         display:grid;place-items:center;height:100vh;margin:0">
            <div style="max-width:440px;text-align:center">
            <h3>Jaeger WebUI is not running</h3>
            <p>\(detail)</p><p>Expected it at <code>\(address)</code>.
            Start it, then choose <b>View › Reload</b> (⌘R).</p></div></body>
            """, baseURL: nil)
    }

    private func retryOrPresent(_ error: Error) {
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain && ns.code == NSURLErrorCancelled { return }
        if ns.domain == "WebKitErrorDomain" && ns.code == 102 { return }  // interrupted by policy (download/external)
        if showingErrorPage { return }
        if loadAttempts < 12 {
            scheduleLoad(after: 0.45)
        } else {
            shellLog("[shell] load failed after \(loadAttempts) attempts: \(ns.localizedDescription)")
            showErrorPage(ns.localizedDescription)
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if !showingErrorPage {
            shellLog("[shell] loaded \(webView.url?.absoluteString ?? "nil")")
            bridgeVerifier?.pageLoaded(webView)
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        retryOrPresent(error)
    }

    func webView(
        _ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error
    ) {
        retryOrPresent(error)
    }

    func webView(
        _ webView: WKWebView,
        runOpenPanelWith parameters: WKOpenPanelParameters,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping ([URL]?) -> Void
    ) {
        guard let window else {
            completionHandler(nil)
            return
        }
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.canChooseFiles = true
        panel.beginSheetModal(for: window) { response in
            completionHandler(response == .OK ? panel.urls : nil)
        }
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        preferences: WKWebpagePreferences,
        decisionHandler: @escaping (WKNavigationActionPolicy, WKWebpagePreferences) -> Void
    ) {
        let url = navigationAction.request.url
        let text = url?.absoluteString ?? "nil"
        switch NavigationPolicy.decide(url, allowed: start.origin) {
        case .allow:
            shellLog("[shell][nav] allow \(text)")
            decisionHandler(navigationAction.shouldPerformDownload ? .download : .allow, preferences)
        case .openExternally:
            shellLog("[shell][nav] external \(text)")
            if let url, navigationAction.navigationType == .linkActivated { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel, preferences)
        case .block:
            shellLog("[shell][nav] blocked \(text)")
            decisionHandler(.cancel, preferences)
        }
    }

    func webView(
        _ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        let url = navigationAction.request.url
        switch NavigationPolicy.decide(url, allowed: start.origin) {
        case .allow: if let url { webView.load(URLRequest(url: url)) }
        case .openExternally: if let url { shellLog("[shell][nav] external \(url.absoluteString)"); NSWorkspace.shared.open(url) }
        case .block: shellLog("[shell][nav] blocked popup \(url?.absoluteString ?? "nil")")
        }
        return nil
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }

    func download(
        _ download: WKDownload,
        decideDestinationUsing response: URLResponse,
        suggestedFilename: String,
        completionHandler: @escaping (URL?) -> Void
    ) {
        guard let window else {
            completionHandler(nil)
            return
        }
        let panel = NSSavePanel()
        panel.nameFieldStringValue = suggestedFilename
        panel.beginSheetModal(for: window) { result in
            completionHandler(result == .OK ? panel.url : nil)
        }
    }

    private func installMainMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem(); main.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Quit Jaeger Shell", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        let viewItem = NSMenuItem(); main.addItem(viewItem)
        let view = NSMenu(title: "View")
        let reload = view.addItem(withTitle: "Reload", action: #selector(reloadShell(_:)), keyEquivalent: "r")
        reload.target = self
        viewItem.submenu = view
        NSApp.mainMenu = main
    }
}

/// Reads the dev-build flag and the overrides (env first, then the
/// uirebuild defaults domain). Production builds ignore overrides.
enum ShellEnvironment {
    static var isDevBuild: Bool { Bundle.main.object(forInfoDictionaryKey: "JaegerDevBuild") as? Bool == true }

    static func webUI() -> StartURL.Resolution {
        StartURL.resolve(
            fallback: StartURL.defaultWebUI,
            envValue: ProcessInfo.processInfo.environment[StartURL.webUIEnvKey],
            defaultsValue: UserDefaults.standard.string(forKey: StartURL.webUIDefaultsKey),
            isDevBuild: isDevBuild)
    }

    static func gateway() -> StartURL.Resolution {
        StartURL.resolve(
            fallback: StartURL.defaultGateway,
            envValue: ProcessInfo.processInfo.environment[StartURL.gatewayEnvKey],
            defaultsValue: UserDefaults.standard.string(forKey: StartURL.gatewayDefaultsKey),
            isDevBuild: isDevBuild)
    }

    static func loginItemStatus() -> String {
        switch SMAppService.mainApp.status {
        case .notRegistered: return "not_registered"
        case .enabled: return "enabled"
        case .requiresApproval: return "requires_approval"
        case .notFound: return "not_found"
        @unknown default: return "unknown"
        }
    }

    /// Launcher for `jaeger stack up` (LauncherResolver, ported from the old BridgeProcess.jaegerPath()).
    static func launcherPath() -> String? {
        LauncherResolver.resolve(
            env: ProcessInfo.processInfo.environment,
            plistLauncher: Bundle.main.object(forInfoDictionaryKey: "JaegerLauncher") as? String,
            bundlePath: Bundle.main.bundlePath, home: NSHomeDirectory(),
            isExecutable: { FileManager.default.isExecutableFile(atPath: $0) })
    }

    /// Opt-in only. Ported (adapted) from jaeger_ai/interfaces/swift/Sources/JaegerAI/MenuCard/LaunchAtLogin.swift:45-62
    /// (guarded register/unregister + refresh). The old init's default registration (lines 24-35, which turned
    /// Launch at Login on for every fresh install) is deliberately NOT ported. Called only from a user action.
    @discardableResult
    static func setLoginItem(_ enabled: Bool) throws -> String {
        let service = SMAppService.mainApp
        if enabled {
            if service.status != .enabled { try service.register() }
        } else {
            if service.status == .enabled { try service.unregister() }
        }
        return loginItemStatus()
    }
}

@main
enum JaegerShellMain {
    static func main() {
        let application = NSApplication.shared
        let delegate = JaegerShellApplication()
        application.delegate = delegate
        application.setActivationPolicy(.accessory)
        application.run()
    }
}
