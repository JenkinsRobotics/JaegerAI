//
//  WebUIChatSurface.swift
//  JaegerAI / ChatWindow
//
//  Canonical chat transcript is the Jaeger WebUI (vendor/hermes-webui on
//  :8790). The Swift window hosts that renderer in WKWebView so Safari
//  and the desktop app do not maintain two activity feeds.
//

import AppKit
import SwiftUI
import WebKit

@MainActor
final class WebUIChatController: ObservableObject {
    static let shared = WebUIChatController()

    @Published private(set) var url: URL?
    @Published private(set) var isLoading = true
    @Published private(set) var lastError: String?
    @Published private(set) var isBusy = false

    fileprivate weak var webView: WKWebView?
    private var pendingSubmit: String?
    private var pendingNewChat = false

    private init() {}

    nonisolated static func profileCookie(for url: URL) -> HTTPCookie? {
        guard let host = url.host, !host.isEmpty else { return nil }
        return HTTPCookie(properties: [
            .domain: host,
            .path: "/",
            .name: "hermes_profile",
            .value: "jaeger",
        ])
    }

    func reload() {
        lastError = nil
        isLoading = true
        Task { await load() }
    }

    func load() async {
        lastError = nil
        isLoading = true
        do {
            let resolved = try await WebUIEndpoint.resolve()
            url = resolved
            applyCookie(for: resolved)
            webView?.load(URLRequest(url: resolved))
        } catch {
            let fallback = URL(string: "http://127.0.0.1:8790/")!
            url = fallback
            applyCookie(for: fallback)
            webView?.load(URLRequest(url: fallback))
        }
    }

    func submit(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        isBusy = true
        defer { isBusy = false }
        if webView == nil {
            pendingSubmit = trimmed
            ChatWindowController.show(agent: AgentBridge.shared, tab: .chat)
            return
        }
        let sent = await injectPrompt(trimmed)
        if !sent {
            pendingSubmit = trimmed
        }
    }

    func requestNewChat() {
        pendingNewChat = true
        Task { await evaluateNewChat() }
    }

    fileprivate func webViewDidFinish() {
        isLoading = false
        applyCookie(for: url ?? webView?.url)
        Task {
            if pendingNewChat {
                pendingNewChat = false
                await evaluateNewChat()
            }
            if let pending = pendingSubmit {
                pendingSubmit = nil
                _ = await injectPrompt(pending)
            }
        }
    }

    fileprivate func webViewFailed(_ message: String) {
        isLoading = false
        lastError = message
    }

    private func applyCookie(for url: URL?) {
        guard let url, let cookie = Self.profileCookie(for: url), let store = webView?.configuration.websiteDataStore.httpCookieStore else { return }
        store.setCookie(cookie)
    }

    private func injectPrompt(_ text: String) async -> Bool {
        guard let webView else { return false }
        let payload = Self.jsonString(text)
        let js = """
        (function(){
          const text = \(payload);
          const ta = document.getElementById('msg') || document.querySelector('textarea');
          if (!ta) return 'no-composer';
          const proto = ta instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          const desc = Object.getOwnPropertyDescriptor(proto, 'value');
          if (desc && desc.set) desc.set.call(ta, text); else ta.value = text;
          ta.dispatchEvent(new Event('input', {bubbles:true}));
          ta.focus();
          const btn = document.querySelector('#btnSend, button[type="submit"], button[aria-label="Send"], .composer-send');
          if (btn && !btn.disabled) { btn.click(); return 'clicked'; }
          ta.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true}));
          return 'enter';
        })()
        """
        do {
            let result = try await webView.evaluateJavaScript(js)
            let token = String(describing: result)
            return token != "no-composer"
        } catch {
            return false
        }
    }

    private func evaluateNewChat() async {
        guard let webView else { return }
        let js = """
        (function(){
          const btn = document.querySelector('[title="New Chat"], [aria-label="New chat"], [data-new-session], button.session-new');
          if (btn) { btn.click(); return 'clicked'; }
          location.href = location.origin + '/';
          return 'reload';
        })()
        """
        _ = try? await webView.evaluateJavaScript(js)
    }

    private static func jsonString(_ text: String) -> String {
        let data = try? JSONSerialization.data(withJSONObject: text, options: .fragmentsAllowed)
        return String(data: data ?? Data("\"\"".utf8), encoding: .utf8) ?? "\"\""
    }
}

struct WebUIChatSurface: NSViewRepresentable {
    @ObservedObject var controller = WebUIChatController.shared

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        config.preferences.isElementFullscreenEnabled = true
        let view = WKWebView(frame: .zero, configuration: config)
        view.setValue(false, forKey: "drawsBackground")
        view.navigationDelegate = context.coordinator
        controller.webView = view
        Task { await controller.load() }
        return view
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {
        controller.webView = nsView
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            WebUIChatController.shared.webViewDidFinish()
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            WebUIChatController.shared.webViewFailed(error.localizedDescription)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            WebUIChatController.shared.webViewFailed(error.localizedDescription)
        }
    }
}

struct WebUIChatContainer: View {
    @ObservedObject private var controller = WebUIChatController.shared

    var body: some View {
        ZStack {
            WebUIChatSurface()
            if controller.isLoading {
                VStack(spacing: 8) {
                    ProgressView()
                    Text("Loading Jaeger chat…")
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color(red: 0.043, green: 0.055, blue: 0.078).opacity(0.72))
            } else if let err = controller.lastError, controller.webViewHasNoPage {
                VStack(spacing: 12) {
                    Text("Jaeger WebUI is not reachable")
                        .font(.system(size: 14, weight: .semibold))
                    Text(err)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                    Button("Retry") { controller.reload() }
                    Button("Open in Safari") {
                        if let url = controller.url { NSWorkspace.shared.open(url) }
                    }
                }
                .padding(24)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }
}

private extension WebUIChatController {
    var webViewHasNoPage: Bool {
        webView?.url == nil
    }
}
