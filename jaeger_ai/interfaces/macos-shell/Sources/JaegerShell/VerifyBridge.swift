// VerifyBridge.swift — `--verify-bridge`: headless end-to-end bridge check (Jaeger original).
//
// Loads the effective WebUI origin in a window that is never shown (no status item, no hotkey),
// drives window.jaegerNative from the page through callAsyncJavaScript, then checks that an
// about:blank iframe and a fixture page on a different origin are rejected. Host actions are
// recorded, never performed (no window shown, no link opened, login item never changed).
// Prints one JSON line to stdout and exits.

import AppKit
import JaegerShellCore
import WebKit

final class BridgeVerifier: NSObject, BridgeHost, WKNavigationDelegate {
    unowned let app: JaegerShellApplication
    private var calls: [String] = []
    private var report: [String: Any] = [:]
    private var ran = false
    private var finished = false
    private var fixture: WKWebView?
    private var fixtureBridge: NativeBridge?
    private var fixtureChrome: StudioWindowChrome?

    init(app: JaegerShellApplication) { self.app = app }

    func startTimeout() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { [weak self] in self?.finish(error: "timeout") }
    }

    // MARK: recording host
    func bridgeShowWindow() { calls.append("window.show"); app.bridge?.send(["type": "window.visibility", "visible": true]) }
    func bridgeHideWindow() { calls.append("window.hide"); app.bridge?.send(["type": "window.visibility", "visible": false]) }
    func bridgeToggleWindow() { calls.append("window.toggle") }
    func bridgeSetPinned(_ pinned: Bool) { calls.append("window.setPinned \(pinned)") }
    func bridgeNotify(title: String, body: String) { calls.append("notify \(title)") }
    func bridgeOpenLink(_ url: URL) { calls.append("link.open \(url.absoluteString) (recorded, not opened)") }
    func bridgeReveal(_ url: URL) { calls.append("file.reveal \(url.path) (recorded)") }
    func bridgeAppInfo() -> [String: Any] { calls.append("app.info"); return ShellEnvironment.appInfo(app.start) }
    func bridgeStackStatus(_ done: @escaping ([String: Any]) -> Void) {
        calls.append("stack.status"); ShellEnvironment.stackStatus(app.start, done)
    }
    func bridgeLoginItemStatus() -> String { calls.append("launchAtLogin.get"); return ShellEnvironment.loginItemStatus() }
    func bridgeSetLoginItem(_ enabled: Bool) throws -> String {
        calls.append("launchAtLogin.set \(enabled) (recorded, not changed)"); return "recorded"
    }

    // MARK: flow
    func pageLoaded(_ webView: WKWebView) {
        guard !ran, let url = webView.url, url.port == app.start.origin.port else { return }
        ran = true
        report["page"] = url.absoluteString
        webView.callAsyncJavaScript(Self.mainScript, arguments: [:], in: nil, in: .page) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let value):
                if let text = value as? String, let obj = try? JSONSerialization.jsonObject(with: Data(text.utf8)) {
                    self.report["js"] = obj
                } else { self.report["js_raw"] = String(describing: value) }
            case .failure(let error): self.report["js_error"] = error.localizedDescription
            }
            self.runWrongOriginFixture()
        }
    }

    private func runWrongOriginFixture() {
        let configuration = WKWebViewConfiguration()
        let bridge = NativeBridge(allowed: app.start.origin, host: self, label: "fixture")
        bridge.install(in: configuration)
        let chrome = StudioWindowChrome()
        chrome.allowedOrigin = app.start.origin
        chrome.install(in: configuration)
        fixtureChrome = chrome
        let webView = WKWebView(frame: NSRect(x: 0, y: 0, width: 200, height: 200), configuration: configuration)
        bridge.webView = webView
        webView.navigationDelegate = self
        fixture = webView
        fixtureBridge = bridge
        let html = """
            <html><body><script>
            window.jaegerNative.post('app.info', {}).then(function(){ document.title = 'replied'; });
            window.webkit.messageHandlers.jaeger.postMessage({id: 'fx-2', type: 'window.show', payload: {}});
            window.webkit.messageHandlers.aetherWindow.postMessage({action: 'drag'});
            </script></body></html>
            """
        let base = URL(string: "http://127.0.0.1:\(app.start.origin.port + 1)/")
        report["fixture_base_url"] = base?.absoluteString
        webView.loadHTMLString(html, baseURL: base)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
            self?.report["fixture_title"] = webView.title ?? ""
            self?.finish(error: nil)
        }
    }

    private func finish(error: String?) {
        guard !finished else { return }
        finished = true
        if let error { report["error"] = error }
        let main = app.bridge
        report["main_accepted"] = main?.accepted ?? -1
        report["main_rejections"] = main?.rejections ?? []
        report["fixture_accepted"] = fixtureBridge?.accepted ?? -1
        report["fixture_rejections"] = fixtureBridge?.rejections ?? []
        report["host_calls"] = calls
        report["window_visible"] = app.mainWindow?.isVisible ?? false
        report["aether_main_accepted"] = app.chrome.accepted
        report["aether_main_rejections"] = app.chrome.rejections
        report["aether_fixture_accepted"] = fixtureChrome?.accepted ?? -1
        report["aether_fixture_rejections"] = fixtureChrome?.rejections ?? []

        let js = report["js"] as? [String: Any] ?? [:]
        func ok(_ key: String) -> Bool? { (js[key] as? [String: Any])?["ok"] as? Bool }
        func err(_ key: String) -> String { (js[key] as? [String: Any])?["error"] as? String ?? "" }
        let checks: [String: Bool] = [
            "host_attr_macos": js["host_attr"] as? String == "macos",
            "app_info_round_trip": ok("app_info") == true,
            "window_hide_round_trip": ok("window_hide") == true,
            "native_event_received": (js["visibility_event"] as? [String: Any])?["visible"] as? Bool == false,
            "link_https_ok": ok("link_https") == true,
            "link_file_refused": ok("link_file") == false,
            "link_js_refused": ok("link_js") == false,
            "reveal_outside_home_refused": ok("reveal_outside_home") == false,
            "mic_stubbed": err("mic").hasPrefix("not_implemented"),
            "unknown_type_refused": err("unknown").hasPrefix("unknown_type"),
            "iframe_rejected": (main?.rejections ?? []).contains { $0.contains("main=false") },
            "wrong_origin_rejected": (fixtureBridge?.accepted ?? -1) == 0 && (fixtureBridge?.rejections.count ?? 0) >= 2,
            "wrong_origin_got_no_reply": (report["fixture_title"] as? String ?? "") != "replied",
            "aether_main_frame_accepted": app.chrome.accepted >= 1,
            "aether_iframe_rejected": app.chrome.rejections.contains { $0.contains("main=false") },
            "aether_wrong_origin_rejected": (fixtureChrome?.accepted ?? -1) == 0 && (fixtureChrome?.rejections.count ?? 0) >= 1,
            "no_window_shown": !(app.mainWindow?.isVisible ?? false) && !calls.contains("window.show"),
        ]
        report["checks"] = checks
        report["ok"] = error == nil && checks.values.allSatisfy { $0 }
        if let data = try? JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]) {
            FileHandle.standardOutput.write(data + Data("\n".utf8))
        }
        NSApp.terminate(nil)
    }

    static let mainScript = """
        const out = {};
        out.host_attr = document.documentElement.getAttribute('data-jaeger-host');
        out.has_api = !!(window.jaegerNative && typeof window.jaegerNative.post === 'function');
        const call = async (t, p) => {
          try { return { ok: true, result: await window.jaegerNative.post(t, p || {}) }; }
          catch (e) { return { ok: false, error: String((e && e.message) || e) }; }
        };
        const vis = new Promise((resolve) => {
          const h = (e) => { if (e.detail && e.detail.type === 'window.visibility') { window.removeEventListener('jaeger:native', h); resolve(e.detail); } };
          window.addEventListener('jaeger:native', h);
          setTimeout(() => resolve(null), 4000);
        });
        out.app_info = await call('app.info');
        out.window_hide = await call('window.hide');
        out.visibility_event = await vis;
        out.link_https = await call('link.open', { url: 'https://example.com/' });
        out.link_file = await call('link.open', { url: 'file:///etc/hosts' });
        out.link_js = await call('link.open', { url: 'javascript:alert(1)' });
        out.reveal_outside_home = await call('file.reveal', { path: '/etc/hosts' });
        out.mic = await call('mic.start', { mode: 'dictation' });
        out.unknown = await call('bogus.type');
        out.login_get = await call('launchAtLogin.get');
        out.stack_status = await call('stack.status');
        const f = document.createElement('iframe');
        f.src = 'about:blank';
        document.body.appendChild(f);
        await new Promise((r) => setTimeout(r, 400));
        try { f.contentWindow.webkit.messageHandlers.jaeger.postMessage({ id: 'iframe-1', type: 'window.show', payload: {} }); out.iframe_posted = true; }
        catch (e) { out.iframe_posted = String(e); }
        try { f.contentWindow.webkit.messageHandlers.aetherWindow.postMessage({ action: 'drag' }); out.aether_iframe_posted = true; }
        catch (e) { out.aether_iframe_posted = String(e); }
        // main frame, allowed origin, harmless unknown action: must pass the origin check, then be ignored
        window.webkit.messageHandlers.aetherWindow.postMessage({ action: 'verify-noop' });
        await new Promise((r) => setTimeout(r, 600));
        f.remove();
        return JSON.stringify(out);
        """
}
