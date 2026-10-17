// VerifyBridge.swift — `--verify-bridge`: headless end-to-end bridge check (Jaeger original).
//
// Loads the effective WebUI origin in a window that is never shown (no status item, no hotkey),
// drives window.jaegerNative from the page through callAsyncJavaScript, then checks that an
// about:blank iframe and a fixture page on a different origin are rejected. Host actions are
// recorded, never performed (no window shown, no link opened, login item never changed).
// Prints one JSON line to stdout and exits.

import AVFoundation
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
    private let renderer = AppleSpeechSynth()
    private var permissionsBefore: [String] = []

    init(app: JaegerShellApplication) { self.app = app }

    private var withDevStack = false
    private var stackLog: [String: Any] = [:]

    func startTimeout(seconds: Double) {
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { [weak self] in self?.finish(error: "timeout") }
    }

    /// --with-dev-stack: start the dev stack (own children), then load the main screen from it.
    func startDevStackThenLoad(_ load: @escaping () -> Void) {
        withDevStack = true
        guard app.stack.dev != nil else {
            finish(error: "dev stack unavailable: \(app.stack.devError?.message ?? "not dev mode")")
            return
        }
        stackLog["ports_free_before"] = devPortsFree()
        let started = Date()
        app.stack.start { [weak self] result, error in
            guard let self else { return }
            self.stackLog["start"] = error.map { ["ok": false, "error": $0] as [String: Any] } ?? ["ok": true, "result": result ?? [:]]
            self.stackLog["start_seconds"] = (Date().timeIntervalSince(started) * 10).rounded() / 10
            if let error { self.finish(error: "dev stack start failed: \(error)") } else { load() }
        }
    }

    private func devPortsFree() -> [String: Bool] {
        guard let dev = app.stack.dev else { return [:] }
        return [String(dev.gatewayPort): !StackController.isListening(dev.gatewayPort),
                String(dev.uiPort): !StackController.isListening(dev.uiPort)]
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
        calls.append("stack.status"); app.stack.status(done)
    }
    /// Real only in dev mode (own children); production is refused here and never invoked.
    func bridgeStackStart(done: @escaping BridgeDone) {
        guard app.stack.dev != nil else { calls.append("stack.start refused (not dev)"); return done(nil, "verify_requires_dev_stack") }
        calls.append("stack.start (dev)"); app.stack.start(done: done)
    }
    func bridgeStackStop(done: @escaping BridgeDone) {
        guard app.stack.dev != nil else { calls.append("stack.stop refused (not dev)"); return done(nil, "verify_requires_dev_stack") }
        calls.append("stack.stop (dev)"); app.stack.stop(done: done)
    }
    func bridgeLoginItemStatus() -> String { calls.append("launchAtLogin.get"); return ShellEnvironment.loginItemStatus() }
    func bridgeSetLoginItem(_ enabled: Bool) throws -> String {
        calls.append("launchAtLogin.set \(enabled) (recorded, not changed)"); return "recorded"
    }
    func bridgeVoiceStatus() -> [String: Any] {
        calls.append("voice.status"); return VoiceController.status(state: "idle", speaking: false)
    }
    func bridgeMicStart(mode: String, done: @escaping BridgeDone) {
        calls.append("mic.start \(mode) (recorded, mic not opened)")
        app.bridge?.send(["type": "voice.state", "state": "listening"])
        done(["listening": false, "recorded": true], nil)
    }
    func bridgeMicStop(done: @escaping BridgeDone) {
        calls.append("mic.stop (recorded)")
        app.bridge?.send(["type": "voice.state", "state": "idle"])
        done(["recorded": true], nil)
    }
    func bridgeTTSSpeak(text: String, voice: String?, done: @escaping BridgeDone) {
        calls.append("tts.speak (silent render, not played)")
        renderer.voiceIdentifier = VoiceCatalog.resolve(voice, installed: VoiceController.installedVoices())
        renderer.render(text: TTSText.plainForSpeech(text)) { [weak self] frames, rate, voiceID in
            self?.app.bridge?.send(["type": "tts.done", "completed": frames > 0, "rendered": true])
            done(["rendered_frames": frames, "sample_rate": rate, "voice": voiceID ?? "none", "played": false], nil)
        }
    }
    func bridgeTTSStop() { calls.append("tts.stop") }
    func bridgeOpenFile(_ url: URL) { calls.append("open.file \(url.path) (recorded, not opened)") }
    func bridgeCopy(_ text: String) { calls.append("clipboard.write \(text.count) chars (recorded, clipboard untouched)") }
    func bridgeMicStatus() -> [String: Any] { calls.append("mic.status"); return VoiceController.micStatus(recording: false) }
    func bridgeTTSStatus() -> [String: Any] { calls.append("tts.status"); return VoiceController.ttsStatus(speaking: false) }

    // MARK: flow
    func pageLoaded(_ webView: WKWebView) {
        guard !ran, let url = webView.url, url.port == app.start.origin.port else { return }
        ran = true
        report["page"] = url.absoluteString
        permissionsBefore = [VoiceController.micPermission(), VoiceController.speechPermission()]
        // appearance.changed for NativeHost.onThemeChanged (the script listens for it)
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { [weak self] in self?.app.sendAppearanceChanged() }
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
            guard let self else { return }
            self.report["fixture_title"] = webView.title ?? ""
            guard self.withDevStack, let main = self.app.mainWebView else { return self.finish(error: nil) }
            // stop the dev stack from the page through the bridge, then check its ports natively
            let body = "try { return JSON.stringify({ ok: true, result: await window.jaegerNative.post('stack.stop') }); } catch (e) { return JSON.stringify({ ok: false, error: String(e) }); }"
            main.callAsyncJavaScript(body, arguments: [:], in: nil, in: .page) { result in
                if case .success(let value) = result, let text = value as? String,
                   let obj = try? JSONSerialization.jsonObject(with: Data(text.utf8)) { self.stackLog["stop_via_bridge"] = obj }
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                    self.stackLog["ports_free_after"] = self.devPortsFree()
                    self.finish(error: nil)
                }
            }
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
        let permissionsAfter = [VoiceController.micPermission(), VoiceController.speechPermission()]
        report["permissions_before"] = permissionsBefore
        report["permissions_after"] = permissionsAfter
        report["window_visible"] = app.mainWindow?.isVisible ?? false
        report["aether_main_accepted"] = app.chrome.accepted
        report["aether_main_rejections"] = app.chrome.rejections
        report["aether_fixture_accepted"] = fixtureChrome?.accepted ?? -1
        report["aether_fixture_rejections"] = fixtureChrome?.rejections ?? []

        let js = report["js"] as? [String: Any] ?? [:]
        func ok(_ key: String) -> Bool? { (js[key] as? [String: Any])?["ok"] as? Bool }
        func err(_ key: String) -> String { (js[key] as? [String: Any])?["error"] as? String ?? "" }
        let baseChecks: [String: Bool] = [
            "host_attr_macos": js["host_attr"] as? String == "macos",
            "app_info_round_trip": ok("app_info") == true,
            "window_hide_round_trip": ok("window_hide") == true,
            "native_event_received": (js["visibility_event"] as? [String: Any])?["visible"] as? Bool == false,
            "link_https_ok": ok("link_https") == true,
            "link_file_refused": ok("link_file") == false,
            "link_js_refused": ok("link_js") == false,
            "reveal_outside_home_refused": ok("reveal_outside_home") == false,
            "voice_status_ok": ok("voice_status") == true && ((js["voice_status"] as? [String: Any])?["result"] as? [String: Any])?["mic_permission"] != nil,
            "mic_start_routed": ok("mic_start") == true,
            "mic_bad_mode_refused": ok("mic_bad_mode") == false,
            "mic_stop_routed": ok("mic_stop") == true,
            "tts_rendered_silently": (((js["tts"] as? [String: Any])?["result"] as? [String: Any])?["rendered_frames"] as? Int ?? 0) > 0,
            "tts_empty_refused": ok("tts_empty") == false,
            "tts_stop_routed": ok("tts_stop") == true,
            "voice_events_received": {
                let events = js["voice_events"] as? [[String: Any]] ?? []
                return events.contains { $0["type"] as? String == "voice.state" && $0["state"] as? String == "listening" }
                    && events.contains { $0["type"] as? String == "tts.done" }
            }(),
            "no_permission_change": permissionsBefore == permissionsAfter && !permissionsBefore.isEmpty,
            "new_ui_loaded": js["new_ui"] as? Bool == true,
            "new_ui_rendered": (js["ui_rendered"] as? Int ?? 0) > 0,
            "hostts_open_external_ok": ok("open_external") == true && calls.contains { $0.hasPrefix("link.open") },
            "hostts_open_file_outside_home_refused": ok("open_file_outside") == false,
            "hostts_clipboard_write_ok": ok("clipboard") == true && calls.contains { $0.hasPrefix("clipboard.write") },
            "hostts_mic_status_ok": ok("mic_status") == true,
            "hostts_tts_status_ok": ok("tts_status") == true,
            "hostts_probe_voice_true": js["probe_voice"] as? Bool == true,
            "hostts_appearance_event": (js["appearance_event"] as? [String: Any])?["type"] as? String == "appearance.changed",
            "unknown_type_refused": err("unknown").hasPrefix("unknown_type"),
            "iframe_rejected": (main?.rejections ?? []).contains { $0.contains("main=false") },
            "wrong_origin_rejected": (fixtureBridge?.accepted ?? -1) == 0 && (fixtureBridge?.rejections.count ?? 0) >= 2,
            "wrong_origin_got_no_reply": (report["fixture_title"] as? String ?? "") != "replied",
            "aether_main_frame_accepted": app.chrome.accepted >= 1,
            "aether_iframe_rejected": app.chrome.rejections.contains { $0.contains("main=false") },
            "aether_wrong_origin_rejected": (fixtureChrome?.accepted ?? -1) == 0 && (fixtureChrome?.rejections.count ?? 0) >= 1,
            "no_window_shown": !(app.mainWindow?.isVisible ?? false) && !calls.contains("window.show"),
        ]
        var allChecks = baseChecks
        if withDevStack {
            report["dev_stack"] = stackLog
            let startResult = (stackLog["start"] as? [String: Any])?["result"] as? [String: Any]
            let statusFromPage = (js["stack_status"] as? [String: Any])?["result"] as? [String: Any]
            let stop = (stackLog["stop_via_bridge"] as? [String: Any])
            let before = stackLog["ports_free_before"] as? [String: Bool] ?? [:]
            let after = stackLog["ports_free_after"] as? [String: Bool] ?? [:]
            let agents = js["agents_http"] as? [String: Any] ?? [:]
            allChecks["dev_ports_free_before_start"] = !before.isEmpty && before.values.allSatisfy { $0 }
            allChecks["dev_stack_start_running"] = startResult?["running"] as? Bool == true
            allChecks["dev_stack_status_running_from_page"] = statusFromPage?["mode"] as? String == "dev" && statusFromPage?["running"] as? Bool == true
            allChecks["ui_loaded_from_dev_stack"] = (report["page"] as? String ?? "").hasPrefix(app.stack.dev!.uiOrigin.string + "/?host=macos")
            allChecks["ui_proxy_reaches_dev_gateway"] = agents["status"] as? Int == 401 && (agents["body"] as? String ?? "").contains("caller token")
            allChecks["dev_stack_stop_via_bridge"] = stop?["ok"] as? Bool == true && (stop?["result"] as? [String: Any])?["stopped"] as? Bool == true
            allChecks["dev_ports_free_after_stop"] = !after.isEmpty && after.values.allSatisfy { $0 }
            allChecks["no_production_stack_call"] = app.stack.productionInvocations == 0
        }
        let checks = allChecks
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
        out.new_ui = document.documentElement.hasAttribute('data-aether-native-window');
        const appearance = new Promise((resolve) => {
          const h = (e) => { if (e.detail && e.detail.type === 'appearance.changed') { window.removeEventListener('jaeger:native', h); resolve(e.detail); } };
          window.addEventListener('jaeger:native', h);
          setTimeout(() => resolve(null), 5000);
        });
        await new Promise((r) => setTimeout(r, 800));
        out.ui_rendered = (document.getElementById('root') || { childElementCount: 0 }).childElementCount;
        out.title = document.title;
        out.ui_text_sample = ((document.getElementById('root') || {}).innerText || '').trim().slice(0, 160);
        out.mic_status = await call('mic.status');
        out.tts_status = await call('tts.status');
        const notImpl = (r) => r == null || r.error === 'not_implemented' || r.status === 'not_implemented';
        out.probe_voice = out.mic_status.ok && out.tts_status.ok && !notImpl(out.mic_status.result) && !notImpl(out.tts_status.result);
        out.open_external = await call('open.external', { url: 'https://example.com/' });
        out.open_file_outside = await call('open.file', { path: '/etc/hosts' });
        out.clipboard = await call('clipboard.write', { text: 'jaeger verify' });
        try {
          const r = await fetch('/v1/agents');
          out.agents_http = { status: r.status, body: (await r.text()).slice(0, 120) };
        } catch (e) { out.agents_http = { error: String(e) }; }
        out.appearance_event = await appearance;
        out.app_info = await call('app.info');
        // armed right before window.hide so slow earlier steps can't eat its timeout
        const vis = new Promise((resolve) => {
          const h = (e) => { if (e.detail && e.detail.type === 'window.visibility') { window.removeEventListener('jaeger:native', h); resolve(e.detail); } };
          window.addEventListener('jaeger:native', h);
          setTimeout(() => resolve(null), 5000);
        });
        out.window_hide = await call('window.hide');
        out.visibility_event = await vis;
        out.link_https = await call('link.open', { url: 'https://example.com/' });
        out.link_file = await call('link.open', { url: 'file:///etc/hosts' });
        out.link_js = await call('link.open', { url: 'javascript:alert(1)' });
        out.reveal_outside_home = await call('file.reveal', { path: '/etc/hosts' });
        out.voice_status = await call('voice.status');
        const voiceEvents = [];
        const vh = (e) => { if (e.detail && (e.detail.type === 'voice.state' || e.detail.type === 'tts.done')) voiceEvents.push(e.detail); };
        window.addEventListener('jaeger:native', vh);
        out.mic_start = await call('mic.start', { mode: 'dictation' });
        out.mic_bad_mode = await call('mic.start', { mode: 'always-on' });
        out.mic_stop = await call('mic.stop');
        out.tts = await call('tts.speak', { text: '**Hello** from the Jaeger shell.', voice: 'female' });
        out.tts_empty = await call('tts.speak', { text: '```' + String.fromCharCode(10) + '```' });
        out.tts_stop = await call('tts.stop');
        await new Promise((r) => setTimeout(r, 300));
        window.removeEventListener('jaeger:native', vh);
        out.voice_events = voiceEvents;
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
