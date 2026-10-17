// Derived from AetherStudio @ ece0209 — Aether CAD/Launcher/AetherCADApplication.swift
// Copyright (c) Jonathan Jenkins and Jenkins Robotics (AetherStudio). Licensed under the Apache License 2.0
// (see LICENSES/AetherStudio-Apache-2.0.txt). Modified for Jaeger by Jenkins Robotics on 2026-10-17:
// renamed; engine spawn (python animacore.httpbridge, .venv, Resources/Web) removed; loads the
// loopback Jaeger WebUI (http://127.0.0.1:8790/?host=macos or the dev override); loopback-only
// navigation + WKContentRuleList; inline "not running" page instead of alert+quit; minimal main
// menu (Quit, Edit, Reload); developer extras only in DEBUG.

import AppKit
import JaegerShellCore
import WebKit
import os

private let shellLogger = Logger(subsystem: "com.jenkinsrobotics.JaegerAI.uirebuild", category: "shell")

/// Public unified-log line (NSLog arguments are redacted) + stderr.
func shellLog(_ message: String) {
    shellLogger.notice("\(message, privacy: .public)")
    FileHandle.standardError.write(Data((message + "\n").utf8))
}

final class JaegerShellApplication: NSObject, NSApplicationDelegate, WKNavigationDelegate,
    WKUIDelegate, WKDownloadDelegate
{
    private var window: NSWindow?
    private var webView: WKWebView?
    private var loadAttempts = 0
    private var showingErrorPage = false
    let start: StartURL.Resolution = ShellEnvironment.webUI()

    func applicationDidFinishLaunching(_ notification: Notification) {
        if let rejected = start.rejected { shellLog("[shell][override] rejected \(rejected)") }
        if let override = start.override { shellLog("[shell][override] accepted \(override)") }
        shellLog("[shell] start_url=\(start.url.absoluteString)")
        installMainMenu()
        showWindow()
        installRulesThenLoad()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    private let windowChrome = StudioWindowChrome()

    func makeWindow() -> NSWindow {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        #if DEBUG
        configuration.preferences.setValue(true, forKey: "developerExtrasEnabled")
        #endif
        windowChrome.install(in: configuration)

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsMagnification = false
        self.webView = webView

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1024, height: 720),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.title = "Jaeger"
        windowChrome.attach(to: window)
        window.setFrameAutosaveName("JaegerShellMainWindow")
        window.contentView = webView
        window.center()
        self.window = window
        return window
    }

    func showWindow() {
        let window = self.window ?? makeWindow()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func installRulesThenLoad() {
        let json = NavigationPolicy.contentRuleListJSON(allowed: start.origin)
        WKContentRuleListStore.default().compileContentRuleList(
            forIdentifier: "jaeger-shell-loopback-\(start.origin.port)", encodedContentRuleList: json
        ) { [weak self] list, error in
            DispatchQueue.main.async {
                guard let self else { return }
                guard let list else {
                    shellLog("[shell] content rule list failed: \(String(describing: error))")
                    self.showErrorPage("The loopback network guard could not be installed.")
                    return
                }
                self.webView?.configuration.userContentController.add(list)
                shellLog("[shell] loopback rule list installed for \(self.start.origin.string)")
                self.scheduleLoad(after: 0.35)
            }
        }
    }

    private func scheduleLoad(after delay: TimeInterval) {
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self else { return }
            self.loadAttempts += 1
            self.showingErrorPage = false
            self.webView?.load(URLRequest(url: self.start.url))
        }
    }

    @objc func reloadShell(_ sender: Any?) {
        loadAttempts = 0
        scheduleLoad(after: 0)
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
        if !showingErrorPage { shellLog("[shell] loaded \(webView.url?.absoluteString ?? "nil")") }
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
}

@main
enum JaegerShellMain {
    static func main() {
        let application = NSApplication.shared
        let delegate = JaegerShellApplication()
        application.delegate = delegate
        application.setActivationPolicy(.regular)
        application.run()
    }
}
