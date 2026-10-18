// VisibleCheck.swift — `--visible-check`: the batched VISIBLE S4/S5 session (Jaeger original).
//
// Runs only when ALL hold: dev build, `--visible-check` argument, JAEGER_SHELL_VISIBLE_CHECK=1
// (Scripts/visible-session-check.sh sets both). Uses the real host (window shown, notification,
// browser, Finder, login item, mic/speech prompts, audible TTS). Every human step is announced in a
// floating on-screen panel (CheckPrompt) BEFORE it runs and waits for the operator (no 3-minute cap;
// each question gives up after 5 min and is recorded). It never invokes "Start Jaeger stack…" (menu
// titles are only read), restores every toggle it changed (pin, launch-at-login, mic, TTS), writes one
// JSON report to $JAEGER_SHELL_CHECK_OUT (else stdout) and quits the app.
// JAEGER_SHELL_CHECK_ONLY=hotkey,speech,notify runs a subset (names: VisibleChecker.stepNames).

import AppKit
import JaegerShellCore
import ServiceManagement
import Speech
import UserNotifications
import WebKit

/// Floating, non-activating operator panel: big title, instructions, optional buttons.
@MainActor
final class CheckPrompt: NSObject {
    private var panel: NSPanel?
    private let titleLabel = NSTextField(labelWithString: "")
    private let textLabel = NSTextField(wrappingLabelWithString: "")
    private let buttonRow = NSStackView()
    private var continuation: CheckedContinuation<String, Never>?
    private var token = 0

    private func ensurePanel() -> NSPanel {
        if let panel { return panel }
        let p = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 500, height: 200),
                        styleMask: [.titled, .nonactivatingPanel, .utilityWindow], backing: .buffered, defer: false)
        p.title = "Jaeger visible check — follow these instructions"
        p.isFloatingPanel = true
        p.level = .statusBar
        p.hidesOnDeactivate = false
        p.isReleasedWhenClosed = false
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        titleLabel.font = .boldSystemFont(ofSize: 20)
        textLabel.font = .systemFont(ofSize: 15)
        textLabel.preferredMaxLayoutWidth = 460
        buttonRow.orientation = .horizontal
        buttonRow.spacing = 12
        let stack = NSStackView(views: [titleLabel, textLabel, buttonRow])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 14
        stack.edgeInsets = NSEdgeInsets(top: 18, left: 20, bottom: 18, right: 20)
        stack.translatesAutoresizingMaskIntoConstraints = false
        let content = NSView()
        content.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            stack.topAnchor.constraint(equalTo: content.topAnchor),
            stack.bottomAnchor.constraint(lessThanOrEqualTo: content.bottomAnchor),
        ])
        p.contentView = content
        if let f = NSScreen.main?.visibleFrame { p.setFrameOrigin(NSPoint(x: f.maxX - 520, y: f.maxY - 230)) }
        panel = p
        return p
    }

    private func display(_ title: String, _ text: String, _ buttons: [String], log: Bool) {
        let p = ensurePanel()
        titleLabel.stringValue = title
        textLabel.stringValue = text
        buttonRow.arrangedSubviews.forEach { $0.removeFromSuperview() }
        for (i, name) in buttons.enumerated() {
            let button = NSButton(title: name, target: self, action: #selector(pressed(_:)))
            button.bezelStyle = .rounded
            if i == 0 { button.keyEquivalent = "\r" }
            buttonRow.addArrangedSubview(button)
        }
        p.orderFrontRegardless()
        if log {
            let options = buttons.isEmpty ? "" : " [\(buttons.joined(separator: " / "))]"
            shellLog("[shell][visible-check] PROMPT \(title) — \(text)\(options)")
        }
    }

    /// Shows a question and waits for a button (or "timeout" after `timeout` seconds).
    func ask(_ title: String, _ text: String, buttons: [String], timeout: Double = 300) async -> String {
        display(title, text, buttons, log: true)
        token += 1
        let mine = token
        Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(timeout * 1e9))
            self?.resolve(mine, "timeout")
        }
        return await withCheckedContinuation { continuation = $0 }
    }

    /// Instruction without buttons (countdowns); stays until the next prompt.
    func notice(_ title: String, _ text: String, log: Bool = true) { display(title, text, [], log: log) }

    func close() { panel?.orderOut(nil) }

    @objc private func pressed(_ sender: NSButton) { resolve(token, sender.title) }

    private func resolve(_ t: Int, _ answer: String) {
        guard t == token, let c = continuation else { return }
        continuation = nil
        shellLog("[shell][visible-check] ANSWER \(answer)")
        c.resume(returning: answer)
    }
}

@MainActor
final class VisibleChecker {
    static let stepNames = ["menu", "close", "pin", "notify", "link", "reveal", "login", "hotkey", "speech", "tts"]

    unowned let app: JaegerShellApplication
    private let prompt = CheckPrompt()
    private var report: [String: Any] = [:]
    private var steps: [[String: Any]] = []
    private var started = false
    private var finished = false
    private var loginOriginalOn: Bool?
    private var loginChanged = false
    private let only: Set<String>

    static var enabled: Bool {
        ShellEnvironment.isDevBuild && CommandLine.arguments.contains("--visible-check")
            && ProcessInfo.processInfo.environment["JAEGER_SHELL_VISIBLE_CHECK"] == "1"
    }

    init(app: JaegerShellApplication) {
        self.app = app
        let raw = ProcessInfo.processInfo.environment["JAEGER_SHELL_CHECK_ONLY"] ?? ""
        only = Set(raw.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces).lowercased() }.filter { !$0.isEmpty })
    }

    private func wants(_ name: String) -> Bool {
        let yes = only.isEmpty || only.contains(name)
        if !yes { shellLog("[shell][visible-check] SKIP \(name) (not in --only)") }
        return yes
    }

    func startTimeout() {
        Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: 40 * 60 * 1_000_000_000)
            await self?.finish(error: "timeout (40 min)")
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

    private func yesNo(_ name: String, _ title: String, _ question: String) async {
        let answer = await prompt.ask(title, question, buttons: ["Yes", "No"])
        step(name, answer == "timeout" ? false : answer == "Yes", answer)
    }

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
            while (true) {
              const hit = window.__vc.events.slice(from).find((e) => e && e.type === t);
              if (hit) return JSON.stringify(hit);
              if (Date.now() >= end) return null;
              await new Promise((r) => setTimeout(r, 100));
            }
            """
        let raw = try? await web.callAsyncJavaScript(
            body, arguments: ["t": type, "from": from, "ms": Int(timeout * 1000)], contentWorld: .page)
        guard let s = raw as? String, let d = s.data(using: .utf8) else { return nil }
        return try? JSONSerialization.jsonObject(with: d) as? [String: Any]
    }

    private func eventCount(_ web: WKWebView) async -> Int {
        (try? await web.callAsyncJavaScript("return window.__vc.events.length;", contentWorld: .page) as? Int) ?? 0
    }

    private func maxLevel(_ web: WKWebView, from: Int) async -> Double {
        let body = "return Math.max(0, ...window.__vc.events.slice(from).filter((e) => e && e.type === 'voice.level').map((e) => Number(e.rms) || 0));"
        let raw = try? await web.callAsyncJavaScript(body, arguments: ["from": from], contentWorld: .page)
        return (raw as? NSNumber)?.doubleValue ?? 0
    }

    private static func notificationAuth(_ s: UNAuthorizationStatus) -> String {
        switch s {
        case .notDetermined: return "not_determined"
        case .denied: return "denied"
        case .authorized: return "authorized"
        case .provisional: return "provisional"
        @unknown default: return "unknown(\(s.rawValue))"
        }
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
        let label = app.hotkeyLabel
        report["hotkey_label"] = label
        report["only"] = only.isEmpty ? "all" : only.sorted().joined(separator: ",")
        report["login_before"] = ShellEnvironment.loginItemStatus()

        let begin = await prompt.ask(
            "Jaeger visible check is starting",
            "Steps: \(only.isEmpty ? Self.stepNames.joined(separator: ", ") : only.sorted().joined(separator: ", ")).\n"
                + "This panel tells you what to do before every step. Never click “Start Jaeger stack…”.",
            buttons: ["Begin", "Cancel"])
        guard begin == "Begin" else { await finish(error: "operator: \(begin) at start"); return }

        // S5.1 menu-bar icon, menu items, status probes (titles read only; Start never invoked)
        if wants("menu") {
            prompt.notice("Checking the menu bar…", "No action needed.")
            if let status = app.statusController {
                status.debugProbe()
                await sleep(2.5)
                let snap = status.debugSnapshot()
                let titles = snap["titles"] as? [String] ?? []
                step("status_item_present", snap["present"] as? Bool == true)
                step("icon_running_with_webui_up", snap["icon"] as? String == "running", snap["icon"] ?? NSNull())
                let expected = ["Show / Hide Jaeger", "Start Jaeger stack…", "Launch at Login", "Reload", "Open in Browser", "Quit Jaeger Shell"]
                step("menu_items", expected.allSatisfy(titles.contains), titles)
                step("webui_probe_running", titles.contains { $0.hasPrefix("Main screen: running") }, titles.first { $0.hasPrefix("Main screen") } ?? "")
                step("gateway_probe_running", titles.contains { $0.hasPrefix("Gateway: running") }, titles.first { $0.hasPrefix("Gateway") } ?? "")
                step("start_never_invoked", true, "Start item present but not triggered")
                await yesNo("menu_icon_seen", "Menu-bar icon", "Is the Jaeger icon visible in the menu bar (top right)? Do not click Start.")
            } else { step("status_item_present", false) }
        }

        // S5.2 hide-on-close
        if wants("close") {
            prompt.notice("Window close test…", "The Jaeger window will hide and come back. No action needed.")
            let n0 = await eventCount(web)
            app.mainWindow?.performClose(nil)
            await sleep(0.8)
            let hiddenEvent = await waitEvent(web, "window.visibility", from: n0, timeout: 2)
            step("close_hides_not_quits", app.mainWindow != nil && app.mainWindow?.isVisible == false
                && hiddenEvent?["visible"] as? Bool == false)
            let shown = await call(web, "window.show")
            await sleep(0.8)
            step("bridge_window_show", shown["ok"] as? Bool == true && app.mainWindow?.isVisible == true)
        }

        if wants("pin") {
            let levelBefore = app.mainWindow?.level ?? .normal
            _ = await call(web, "window.setPinned", ["pinned": true])
            let pinned = app.mainWindow?.level == .floating
            _ = await call(web, "window.setPinned", ["pinned": false])
            step("setPinned_then_restored", pinned && app.mainWindow?.level == .normal && levelBefore == .normal)
        }

        // real notification: FAILS unless macOS reports it authorised
        if wants("notify") {
            let center = UNUserNotificationCenter.current()
            let before = await center.notificationSettings().authorizationStatus
            if before == .notDetermined {
                _ = await prompt.ask("Notification test",
                                     "macOS may ask whether JaegerShell can send notifications. Click Allow, then a test banner appears.",
                                     buttons: ["Continue"])
            } else {
                prompt.notice("Notification test", "Watch the top-right corner for a banner titled “Jaeger visible check”.")
            }
            let note = await call(web, "notify", ["title": "Jaeger visible check", "body": "If you can see this, notify works."])
            await sleep(2.5)
            let after = await center.notificationSettings().authorizationStatus
            let granted = after == .authorized || after == .provisional
            let auth = ["before": Self.notificationAuth(before), "after": Self.notificationAuth(after)]
            report["notification_permission"] = auth
            step("notify_authorized", granted, auth)
            step("notify_sent", note["ok"] as? Bool == true && granted, note)
            if granted {
                await yesNo("notify_banner_seen", "Notification test", "Did a banner titled “Jaeger visible check” appear?")
            } else {
                _ = await prompt.ask("Notifications are off for JaegerShell",
                                     "macOS reports \(auth["after"]!). To enable: System Settings › Notifications › JaegerShell › Allow notifications. Then rerun with --only notify.",
                                     buttons: ["OK"], timeout: 120)
                step("notify_banner_seen", false, "not authorised (\(auth["after"]!))")
            }
        }

        if wants("link") {
            prompt.notice("Link test", "example.com will open in your default browser.")
            let link = await call(web, "link.open", ["url": "https://example.com/"])
            step("link_open", link["ok"] as? Bool == true, link)
            await sleep(1.5)
            await yesNo("link_opened_seen", "Link test", "Did https://example.com open in your browser?")
        }

        if wants("reveal") {
            let revealPath = ProcessInfo.processInfo.environment["JAEGER_SHELL_CHECK_REVEAL"] ?? ""
            prompt.notice("Finder test", "Finder will show visible-check-reveal.txt.")
            let reveal = await call(web, "file.reveal", ["path": revealPath])
            step("file_reveal", reveal["ok"] as? Bool == true, ["path": revealPath, "reply": reveal])
            await sleep(1.5)
            await yesNo("file_reveal_seen", "Finder test", "Did Finder show visible-check-reveal.txt selected?")
            app.showWindow()
        }

        // launch-at-login toggle → restore (compared as on/off: not_found and not_registered are both off)
        if wants("login") {
            prompt.notice("Launch at Login test", "It is switched on and straight back off. macOS may show a “Login Items” notice — that is expected.")
            let original = ShellEnvironment.loginItemStatus()
            let wasOn = original == "enabled"
            loginOriginalOn = wasOn
            let flip = await call(web, "launchAtLogin.set", ["enabled": !wasOn])
            loginChanged = flip["ok"] as? Bool == true
            let mid = ShellEnvironment.loginItemStatus()
            let back = await call(web, "launchAtLogin.set", ["enabled": wasOn])
            let final = ShellEnvironment.loginItemStatus()
            if back["ok"] as? Bool == true, (final == "enabled") == wasOn { loginChanged = false }
            step("launchAtLogin_toggle", (mid == "enabled") != wasOn, ["original": original, "flip": flip, "mid": mid])
            step("launchAtLogin_restored", (final == "enabled") == wasOn,
                 ["original": original, "final": final, "on_before": wasOn, "on_after": final == "enabled"])
        }

        // global hotkey → page event
        if wants("hotkey") {
            let ready = await prompt.ask("Hotkey test",
                                         "Click Ready, then press \(label) (Control + Option + Space) once. You will have 20 seconds.",
                                         buttons: ["Ready", "Skip"])
            if ready == "Ready" {
                let n1 = await eventCount(web)
                var hit: [String: Any]?
                for left in stride(from: 20, to: 0, by: -1) {
                    prompt.notice("Press \(label) now", "\(left) s left…", log: left == 20)
                    if let h = await waitEvent(web, "hotkey", from: n1, timeout: 1) { hit = h; break }
                }
                if hit != nil {
                    step("hotkey_event_reached_page", true)
                } else {
                    let pressed = await prompt.ask("Hotkey not received", "Did you press \(label)?",
                                                   buttons: ["Yes, I pressed it", "No / missed it"])
                    step("hotkey_event_reached_page", false,
                         pressed.hasPrefix("Yes") ? "pressed but not received (swallowed before Carbon?)" : "not pressed (\(pressed))")
                }
            } else {
                step("hotkey_event_reached_page", false, "skipped by operator (\(ready))")
            }
            app.showWindow()
        }

        // mic + STT: instructions and permissions FIRST, then countdown, then record ~6 s
        if wants("speech") {
            let ready = await prompt.ask("Speech test",
                                         "1. Click Ready.\n2. If macOS asks for Microphone or Speech Recognition access, click Allow.\n3. A 3-2-1 countdown follows; at SPEAK NOW say “testing one two three” (about 6 s).",
                                         buttons: ["Ready", "Skip"])
            if ready == "Ready" {
                prompt.notice("Speech test", "Checking Microphone and Speech Recognition access — click Allow if asked.")
                let micOK = await withCheckedContinuation { c in VoiceRecorder.requestMicrophoneAccess { c.resume(returning: $0) } }
                let speech = await withCheckedContinuation { c in SFSpeechRecognizer.requestAuthorization { c.resume(returning: $0) } }
                let perms = ["mic": VoiceController.micPermission(), "speech": VoiceController.speechPermission()]
                report["voice_permissions"] = perms
                step("mic_permission", micOK, perms["mic"]!)
                step("speech_permission", speech == .authorized, perms["speech"]!)
                if micOK {
                    for c in [3, 2, 1] {
                        prompt.notice("Get ready to speak", "Recording starts in \(c)…")
                        await sleep(1)
                    }
                    let n2 = await eventCount(web)
                    let mic = await call(web, "mic.start", ["mode": "dictation"])
                    step("mic_start", mic["ok"] as? Bool == true, mic)
                    if mic["ok"] as? Bool == true {
                        for left in stride(from: 6, to: 0, by: -1) {
                            prompt.notice("SPEAK NOW", "Say: “testing one two three” — \(left) s", log: left == 6)
                            await sleep(1)
                        }
                        let stop = await call(web, "mic.stop")
                        step("mic_stop", stop["ok"] as? Bool == true, stop)
                        prompt.notice("Speech test", "Recording stopped. Transcribing…")
                        let level = await maxLevel(web, from: n2)
                        step("mic_level_events", level > 0, ["max_rms": level])
                        let transcript = await waitEvent(web, "voice.transcript", from: n2, timeout: 20)
                        let voiceError = transcript == nil ? await waitEvent(web, "voice.error", from: n2, timeout: 0.5) : nil
                        let text = transcript?["text"] as? String ?? ""
                        report["transcript"] = text
                        step("stt_transcript", !text.isEmpty, (transcript as Any?) ?? (voiceError as Any?) ?? "none")
                        step("stt_transcript_matches", text.lowercased().contains("test"), text)
                    }
                }
            } else {
                step("mic_start", false, "skipped by operator (\(ready))")
            }
            report["permissions_after_mic"] = [VoiceController.micPermission(), VoiceController.speechPermission()]
        }

        // audible TTS
        if wants("tts") {
            prompt.notice("Speech output test", "Listen: the Mac will say “Jaeger voice check complete.”")
            let n3 = await eventCount(web)
            let tts = await call(web, "tts.speak", ["text": "Jaeger voice check complete.", "voice": "female"])
            let done = await waitEvent(web, "tts.done", from: n3, timeout: 15)
            step("tts_speak_audible", tts["ok"] as? Bool == true && done?["completed"] as? Bool == true,
                 ["reply": tts, "done": (done as Any?) ?? NSNull()] as [String: Any])
            await yesNo("tts_heard", "Speech output test", "Did you hear “Jaeger voice check complete.”?")
        }

        prompt.notice("Done", "All steps finished. JaegerShell will quit now; results are in the terminal.")
        await sleep(2)
        await finish(error: nil)
    }

    /// Restores every toggle, writes the report, quits.
    func finish(error: String?) async {
        guard !finished else { return }
        finished = true
        prompt.close()
        app.mainWindow?.level = .normal
        app.bridgeTTSStop()
        if app.voiceController?.isRecording == true { app.voiceController?.micStop { _, _ in } }
        if loginChanged, let loginOriginalOn {
            _ = try? ShellEnvironment.setLoginItem(loginOriginalOn)
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
