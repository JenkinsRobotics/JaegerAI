// VisibleCheck.swift — `--visible-check`: the batched VISIBLE S4/S5 session (Jaeger original).
//
// Runs only when ALL hold: dev build, `--visible-check` argument, JAEGER_SHELL_VISIBLE_CHECK=1
// (Scripts/visible-session-check.sh sets both). Uses the real host (window shown, notification,
// browser, Finder, login item, mic/speech prompts, audible TTS). It never invokes "Start Jaeger stack…"
// (menu titles are only read), restores every toggle it changed (pin, launch-at-login, mic, TTS),
// writes one JSON report to $JAEGER_SHELL_CHECK_OUT (else stdout) and quits the app.

import AppKit
import JaegerShellCore
import ServiceManagement
import UserNotifications
import WebKit

@MainActor
final class VisibleChecker {
    unowned let app: JaegerShellApplication
    private var report: [String: Any] = [:]
    private var steps: [[String: Any]] = []
    private var started = false
    private var finished = false
    private var loginOriginal: String?
    private var loginChanged = false

    static var enabled: Bool {
        ShellEnvironment.isDevBuild && CommandLine.arguments.contains("--visible-check")
            && ProcessInfo.processInfo.environment["JAEGER_SHELL_VISIBLE_CHECK"] == "1"
    }

    init(app: JaegerShellApplication) { self.app = app }

    func startTimeout() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 300) { [weak self] in
            Task { @MainActor in await self?.finish(error: "timeout") }
        }
    }

    func pageLoaded(_ webView: WKWebView) {
        guard !started else { return }
        started = true
        Task { @MainActor in await run(webView) }
    }

    private func step(_ name: String, _ ok: Bool?, _ detail: Any = NSNull()) {
        let mark = ok == nil ? "MANUAL" : (ok! ? "PASS" : "FAIL")
        shellLog("[shell][visible-check] \(mark) \(name) \(detail)")
        steps.append(["step": name, "ok": ok.map { $0 as Any } ?? NSNull(), "detail": detail])
    }

    private func sleep(_ seconds: Double) async { try? await Task.sleep(nanoseconds: UInt64(seconds * 1e9)) }

    /// Calls the bridge from the page exactly as the WebUI would.
    private func call(_ web: WKWebView, _ type: String, _ payload: [String: Any] = [:]) async -> [String: Any] {
        let body = "return JSON.stringify(await window.__vc.call(t, p));"
        do {
            let raw = try await web.callAsyncJavaScript(body, arguments: ["t": type, "p": payload], contentWorld: .page)
            if let s = raw as? String, let d = s.data(using: .utf8),
               let obj = try? JSONSerialization.jsonObject(with: d) as? [String: Any] { return obj }
            return ["ok": false, "error": "bad reply"]
        } catch { return ["ok": false, "error": "js: \(error.localizedDescription)"] }
    }

    /// Waits for a jaeger:native event of `type` that arrived after index `from`.
    private func waitEvent(_ web: WKWebView, _ type: String, from: Int, timeout: Double) async -> [String: Any]? {
        let body = """
            const end = Date.now() + ms;
            while (Date.now() < end) {
              const hit = window.__vc.events.slice(from).find((e) => e && e.type === t);
              if (hit) return JSON.stringify(hit);
              await new Promise((r) => setTimeout(r, 100));
            }
            return null;
            """
        let raw = try? await web.callAsyncJavaScript(
            body, arguments: ["t": type, "from": from, "ms": Int(timeout * 1000)], contentWorld: .page)
        guard let s = raw as? String, let d = s.data(using: .utf8) else { return nil }
        return try? JSONSerialization.jsonObject(with: d) as? [String: Any]
    }

    private func eventCount(_ web: WKWebView) async -> Int {
        (try? await web.callAsyncJavaScript("return window.__vc.events.length;", contentWorld: .page) as? Int) ?? 0
    }

    private func run(_ web: WKWebView) async {
        let setup = """
            window.__vc = { events: [] };
            window.addEventListener('jaeger:native', (e) => window.__vc.events.push(e.detail));
            window.__vc.call = async (t, p) => {
              try { return { ok: true, result: await window.jaegerNative.post(t, p || {}) }; }
              catch (e) { return { ok: false, error: String((e && e.message) || e) }; }
            };
            return !!(window.jaegerNative && typeof window.jaegerNative.post === 'function');
            """
        let hasAPI = (try? await web.callAsyncJavaScript(setup, contentWorld: .page) as? Bool) ?? false
        step("bridge_api_present", hasAPI)
        report["hotkey_label"] = app.hotkeyLabel
        report["login_before"] = ShellEnvironment.loginItemStatus()

        // S5.1 menu-bar icon, menu items, status probes (menu titles only read; Start never invoked)
        if let status = app.statusController {
            status.debugProbe()
            await sleep(2.5)
            let snap = status.debugSnapshot()
            let titles = snap["titles"] as? [String] ?? []
            step("status_item_present", snap["present"] as? Bool == true)
            step("icon_running_with_webui_up", snap["icon"] as? String == "running", snap["icon"] ?? NSNull())
            let expected = ["Show / Hide Jaeger", "Start Jaeger stack…", "Launch at Login", "Reload", "Open in Browser", "Quit Jaeger Shell"]
            step("menu_items", expected.allSatisfy(titles.contains), titles)
            step("webui_probe_running", titles.contains { $0.hasPrefix("WebUI: running") }, titles.first { $0.hasPrefix("WebUI") } ?? "")
            step("gateway_probe_running", titles.contains { $0.hasPrefix("Gateway: running") }, titles.first { $0.hasPrefix("Gateway") } ?? "")
            step("start_never_invoked", true, "Start item present but not triggered")
        } else { step("status_item_present", false) }

        // S5.2 hide-on-close
        let n0 = await eventCount(web)
        app.mainWindow?.performClose(nil)
        await sleep(0.8)
        let hiddenEvent = await waitEvent(web, "window.visibility", from: n0, timeout: 2)
        step("close_hides_not_quits", app.mainWindow != nil && app.mainWindow?.isVisible == false
            && hiddenEvent?["visible"] as? Bool == false)
        let shown = await call(web, "window.show")
        await sleep(0.8)
        step("bridge_window_show", shown["ok"] as? Bool == true && app.mainWindow?.isVisible == true)

        // pin → restore
        let levelBefore = app.mainWindow?.level ?? .normal
        _ = await call(web, "window.setPinned", ["pinned": true])
        let pinned = app.mainWindow?.level == .floating
        _ = await call(web, "window.setPinned", ["pinned": false])
        step("setPinned_then_restored", pinned && app.mainWindow?.level == .normal && levelBefore == .normal)

        // real notification (first run: macOS notification permission prompt)
        let note = await call(web, "notify", ["title": "Jaeger visible check", "body": "If you can see this, notify works."])
        await sleep(2)
        let auth = await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
        step("notify_sent", note["ok"] as? Bool == true, ["reply": note, "authorization": auth.rawValue])
        step("notify_banner_seen", nil, "operator: a 'Jaeger visible check' banner appeared")

        // real link.open + file.reveal
        let link = await call(web, "link.open", ["url": "https://example.com/"])
        step("link_open", link["ok"] as? Bool == true, "operator: example.com opened in the default browser")
        let revealPath = ProcessInfo.processInfo.environment["JAEGER_SHELL_CHECK_REVEAL"] ?? ""
        let reveal = await call(web, "file.reveal", ["path": revealPath])
        step("file_reveal", reveal["ok"] as? Bool == true, ["path": revealPath, "reply": reveal])
        await sleep(1.5)
        app.showWindow()

        // launch-at-login toggle → restore
        let original = ShellEnvironment.loginItemStatus()
        loginOriginal = original
        let wasOn = original == "enabled"
        let flip = await call(web, "launchAtLogin.set", ["enabled": !wasOn])
        loginChanged = flip["ok"] as? Bool == true
        let mid = ShellEnvironment.loginItemStatus()
        let back = await call(web, "launchAtLogin.set", ["enabled": wasOn])
        let final = ShellEnvironment.loginItemStatus()
        if back["ok"] as? Bool == true { loginChanged = false }
        step("launchAtLogin_toggle", (mid == "enabled") != wasOn, ["original": original, "flip": flip, "mid": mid])
        step("launchAtLogin_restored", (final == "enabled") == wasOn, ["final": final, "restore": back])

        // global hotkey → page event
        let n1 = await eventCount(web)
        shellLog("[shell][visible-check] ACTION press \(app.hotkeyLabel) now (20 s)")
        let hot = await waitEvent(web, "hotkey", from: n1, timeout: 20)
        step("hotkey_event_reached_page", hot != nil)
        app.showWindow()

        // mic + STT (macOS microphone and speech-recognition prompts) → stop
        shellLog("[shell][visible-check] ACTION allow the mic/speech prompts, then say 'testing one two three'")
        let n2 = await eventCount(web)
        let mic = await call(web, "mic.start", ["mode": "dictation"])
        step("mic_start", mic["ok"] as? Bool == true, mic)
        if mic["ok"] as? Bool == true {
            await sleep(6)
            let stop = await call(web, "mic.stop")
            step("mic_stop", stop["ok"] as? Bool == true, stop)
            let transcript = await waitEvent(web, "voice.transcript", from: n2, timeout: 20)
            let voiceError = transcript == nil ? await waitEvent(web, "voice.error", from: n2, timeout: 0.5) : nil
            step("stt_transcript", transcript != nil, transcript ?? voiceError ?? "none")
            let level = await waitEvent(web, "voice.level", from: n2, timeout: 0.5)
            step("mic_level_events", level != nil)
        }
        report["permissions_after_mic"] = [VoiceController.micPermission(), VoiceController.speechPermission()]

        // audible TTS
        let n3 = await eventCount(web)
        let tts = await call(web, "tts.speak", ["text": "Jaeger voice check complete.", "voice": "female"])
        let done = await waitEvent(web, "tts.done", from: n3, timeout: 15)
        step("tts_speak_audible", tts["ok"] as? Bool == true && done?["completed"] as? Bool == true, ["reply": tts, "done": (done as Any?) ?? NSNull()] as [String: Any])
        step("tts_heard", nil, "operator: heard 'Jaeger voice check complete.'")

        await finish(error: nil)
    }

    /// Restores every toggle, writes the report, quits.
    func finish(error: String?) async {
        guard !finished else { return }
        finished = true
        app.mainWindow?.level = .normal
        app.bridgeTTSStop()
        if app.voiceController?.isRecording == true { app.voiceController?.micStop { _, _ in } }
        if loginChanged, let loginOriginal {
            _ = try? ShellEnvironment.setLoginItem(loginOriginal == "enabled")
        }
        report["login_after"] = ShellEnvironment.loginItemStatus()
        report["steps"] = steps
        report["error"] = error ?? NSNull()
        report["ok"] = error == nil && steps.allSatisfy { ($0["ok"] as? Bool) != false }
        let data = (try? JSONSerialization.data(withJSONObject: report, options: [.sortedKeys, .prettyPrinted])) ?? Data()
        if let out = ProcessInfo.processInfo.environment["JAEGER_SHELL_CHECK_OUT"], !out.isEmpty {
            try? data.write(to: URL(fileURLWithPath: out))
        } else {
            FileHandle.standardOutput.write(data + Data("\n".utf8))
        }
        shellLog("[shell][visible-check] done ok=\(report["ok"] ?? false) — quitting")
        NSApp.terminate(nil)
    }
}
