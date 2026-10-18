// Snapshot.swift — `--snapshot <dir>`: headless screenshots of the main window (Jaeger original, 2026-10-17).
//
// Loads the effective main-screen origin in a real 1040×760 window placed far off every display (never on
// Matthew's screen; no menu, status item, hotkey or activation), then for light and dark: sets the window
// appearance, waits for the page to restyle, takes WKWebView.takeSnapshot and composites the real traffic-light
// buttons (cacheDisplay) at their window frames with the window's corner radius. Writes
// <dir>/jaeger-light.png and <dir>/jaeger-dark.png, prints one JSON line (chrome report + page probe), exits.
// Optional `--snapshot-size WxH` (clamped to the window minimum) shoots another window size.
// Optional, repeatable `--snapshot-click <css selector>` clicks the first match of each selector in order
// (0.8 s apart) before the shots, e.g. to open another chat or expand a fold; `scrollTop:<selector>` scrolls
// that element to the top instead; `focus:<selector>` focuses it; `type:<selector>|<text>` focuses a text field and
// sets its value the way typing would (React sees an input event; `\n` in the text is a newline). Acts only
// inside the page. The report lists every window the process owns (AppKit's list and the window server's list
// for this PID) after load and after the actions, so stray windows show up by class, size and level.
// Host actions from the page are recorded, never performed.

import AppKit
import JaegerShellCore
import WebKit

/// Keeps its frame wherever it is put (AppKit would pull an off-screen frame back onto a display).
final class OffscreenSnapshotWindow: NSWindow {
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect { frameRect }
}

final class Snapshotter: NSObject, BridgeHost {
    unowned let app: JaegerShellApplication
    let dir: URL
    private var calls: [String] = []
    private var report: [String: Any] = [:]
    private var shots: [String: Any] = [:]
    private var loaded = false
    private var finished = false
    static let offscreenOrigin = NSPoint(x: -20000, y: -20000)

    init(app: JaegerShellApplication, dir: String) {
        self.app = app
        self.dir = URL(fileURLWithPath: dir, isDirectory: true)
    }

    func start() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 60) { [weak self] in self?.finish(error: "timeout") }
        do { try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true) }
        catch { return finish(error: "cannot create \(dir.path): \(error.localizedDescription)") }
        guard let window = app.mainWindow else { return finish(error: "no window") }
        if let size = Self.requestedSize() {
            window.setContentSize(NSSize(width: max(size.width, window.minSize.width),
                                         height: max(size.height, window.minSize.height)))
        }
        window.setFrameOrigin(Self.offscreenOrigin)
        window.collectionBehavior.insert([.transient, .ignoresCycle])
        window.ignoresMouseEvents = true
        window.orderFrontRegardless()  // ordered in so WebKit renders; the frame is off every display
        NativeChrome.layoutTrafficLights(window)
        report["window_on_any_screen"] = NSScreen.screens.contains { $0.frame.intersects(window.frame) }
        report["app_active"] = NSApp.isActive
    }

    static func requestedSize() -> NSSize? {
        let a = CommandLine.arguments
        guard let i = a.firstIndex(of: "--snapshot-size"), i + 1 < a.count else { return nil }
        let parts = a[i + 1].lowercased().split(separator: "x").compactMap { Double($0) }
        guard parts.count == 2, parts[0] > 0, parts[1] > 0 else { return nil }
        return NSSize(width: parts[0], height: parts[1])
    }

    static func requestedClicks() -> [String] {
        let a = CommandLine.arguments
        return a.indices.compactMap { i in a[i] == "--snapshot-click" && i + 1 < a.count ? a[i + 1] : nil }
    }

    func pageLoaded(_ webView: WKWebView) {
        guard !loaded else { return }
        loaded = true
        report["url"] = webView.url?.absoluteString ?? "nil"
        report["windows_after_load"] = Self.windowCensus()
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) { [weak self] in
            // An off-screen window doesn't run CSS transitions or animations, so a still would freeze mid-fade
            // (or at opacity 0); stills show every transition and animation at its end state.
            webView.evaluateJavaScript(Self.stillsCSS) { _, _ in self?.click(Self.requestedClicks(), webView: webView) }
        }
    }

    private func click(_ selectors: [String], webView: WKWebView) {
        guard let selector = selectors.first else {
            report["windows_after_actions"] = Self.windowCensus()
            return capture(["light", "dark"], webView: webView)
        }
        let literal = String(data: (try? JSONSerialization.data(withJSONObject: [selector])) ?? Data("[\"\"]".utf8), encoding: .utf8) ?? "[\"\"]"
        // "scrollTop:<selector>" scrolls that element to the top instead of clicking it.
        let js = """
            (() => { let s = \(literal)[0], text = null; const kind = (s.match(/^(scrollTop|focus|type):/) || [])[1] || 'click';
              if (kind !== 'click') s = s.slice(kind.length + 1);
              if (kind === 'type') { const bar = s.indexOf('|'); text = s.slice(bar + 1).replace(/\\\\n/g, '\\n'); s = s.slice(0, bar); }
              const el = document.querySelector(s); if (!el) return false;
              if (kind === 'scrollTop') { el.scrollTop = 0; el.dispatchEvent(new Event('scroll')); }
              else if (kind === 'focus') el.focus();
              else if (kind === 'type') {
                el.focus();
                const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, text);
                el.dispatchEvent(new Event('input', { bubbles: true }));
              } else el.click();
              return true; })()
            """
        webView.evaluateJavaScript(js) { [weak self] result, _ in
            guard let self else { return }
            var clicks = self.report["clicks"] as? [[String: Any]] ?? []
            clicks.append(["selector": selector, "clicked": (result as? Bool) ?? false])
            self.report["clicks"] = clicks
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                self.click(Array(selectors.dropFirst()), webView: webView)
            }
        }
    }

    private func capture(_ remaining: [String], webView: WKWebView) {
        guard let name = remaining.first else { return finish(error: nil) }
        guard let window = app.mainWindow else { return finish(error: "no window") }
        let appearance = NSAppearance(named: name == "dark" ? .darkAqua : .aqua)!
        window.appearance = appearance
        NativeChrome.applyAppearance(window, webView: webView)
        app.sendAppearanceChanged(name)
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
            guard let self else { return }
            NativeChrome.layoutTrafficLights(window)
            webView.evaluateJavaScript(Self.probeJS) { probe, _ in
                let config = WKSnapshotConfiguration()
                config.afterScreenUpdates = true
                webView.takeSnapshot(with: config) { image, error in
                    var entry: [String: Any] = ["page": Self.decode(probe)]
                    if let image, let png = Self.composite(image, window: window, appearance: appearance) {
                        let url = self.dir.appendingPathComponent("jaeger-\(name).png")
                        do {
                            try png.write(to: url)
                            entry["path"] = url.path
                            entry["pixels"] = Self.pixelSize(png)
                        } catch { entry["error"] = error.localizedDescription }
                    } else {
                        entry["error"] = "snapshot failed: \(error?.localizedDescription ?? "no image")"
                    }
                    entry["chrome"] = NativeChrome.report(window, webView: webView)
                    self.shots[name] = entry
                    self.capture(Array(remaining.dropFirst()), webView: webView)
                }
            }
        }
    }

    static let stillsCSS = """
        (() => { const s = document.createElement('style'); s.dataset.snapshot = 'stills';
          s.textContent = '*, *::before, *::after { transition: none !important; animation-duration: 0s !important; animation-iteration-count: 1 !important; animation-delay: 0s !important; }';
          document.head.append(s); return true; })()
        """

    static let probeJS = """
        (() => {
          const d = document.documentElement, cs = getComputedStyle(d), b = getComputedStyle(document.body);
          const v = (n) => cs.getPropertyValue(n).trim();
          return JSON.stringify({
            host: d.getAttribute('data-jaeger-host'), vibrancy: d.getAttribute('data-native-vibrancy'),
            band: v('--jaeger-native-band-height'), reserve: v('--jaeger-native-traffic-light-reserve'),
            titlebar: v('--jaeger-native-titlebar-height'), traffic_light_width: v('--jaeger-native-traffic-light-width'),
            body_background: b.backgroundColor, html_background: cs.backgroundColor,
            prefers_dark: matchMedia('(prefers-color-scheme: dark)').matches,
            viewport: [innerWidth, innerHeight], title: document.title,
            chat_scroll: (() => { const e = document.querySelector('.jg-chat__scroll'); return e ? [e.scrollTop, e.scrollHeight, e.clientHeight, getComputedStyle(e).overflowY] : null; })(),
            jump: (document.querySelector('.jg-jump') || {}).className || null,
            composer: (() => { const t = document.querySelector('.jg-composer__input'), f = document.querySelector('.jg-composer');
              if (!t || !f) return null; const r = t.getBoundingClientRect(), cs = getComputedStyle(t);
              return { lines: t.value ? t.value.split('\\n').length : 0, textarea_height: Math.round(r.height), scroll_height: t.scrollHeight,
                max_height: cs.maxHeight, overflow_y: cs.overflowY, form_height: Math.round(f.getBoundingClientRect().height),
                form_bottom_gap: Math.round(innerHeight - f.getBoundingClientRect().bottom), focused: document.activeElement === t }; })(),
            text_sample: (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 160)
          });
        })()
        """

    /// Every window this process owns: AppKit's view (class, title, frame, visible, level) and the window
    /// server's (number, bounds, layer, on screen) for our PID, which also catches windows AppKit's
    /// subsystems (text input, WebKit) create.
    static func windowCensus() -> [String: Any] {
        let appkit: [[String: Any]] = NSApp.windows.map { w in
            ["class": String(describing: type(of: w)), "bundle": Bundle(for: type(of: w)).bundleURL.lastPathComponent, "title": w.title, "number": w.windowNumber,
             "frame": [Int(w.frame.minX), Int(w.frame.minY), Int(w.frame.width), Int(w.frame.height)],
             "visible": w.isVisible, "level": w.level.rawValue, "main": w === NSApp.mainWindow || w.contentView is WKWebView]
        }
        let pid = ProcessInfo.processInfo.processIdentifier
        let info = CGWindowListCopyWindowInfo([.optionAll], kCGNullWindowID) as? [[String: Any]] ?? []
        let server: [[String: Any]] = info.filter { ($0[kCGWindowOwnerPID as String] as? Int32) == pid }.map { w in
            let b = w[kCGWindowBounds as String] as? [String: CGFloat] ?? [:]
            return ["number": w[kCGWindowNumber as String] as? Int ?? -1, "layer": w[kCGWindowLayer as String] as? Int ?? 0,
                    "onscreen": w[kCGWindowIsOnscreen as String] as? Bool ?? false,
                    "bounds": [Int(b["X"] ?? 0), Int(b["Y"] ?? 0), Int(b["Width"] ?? 0), Int(b["Height"] ?? 0)]]
        }
        return ["appkit": appkit, "server": server]
    }

    static func decode(_ any: Any?) -> Any {
        guard let s = any as? String, let d = s.data(using: .utf8),
              let o = try? JSONSerialization.jsonObject(with: d) else { return NSNull() }
        return o
    }

    static func pixelSize(_ png: Data) -> [Int] {
        guard let rep = NSBitmapImageRep(data: png) else { return [] }
        return [rep.pixelsWide, rep.pixelsHigh]
    }

    /// Page snapshot + the real traffic-light buttons, clipped to the window's rounded corners.
    static func composite(_ snapshot: NSImage, window: NSWindow, appearance: NSAppearance) -> Data? {
        let size = window.frame.size
        let scale = max(window.backingScaleFactor, 2)
        guard let rep = NSBitmapImageRep(
            bitmapDataPlanes: nil, pixelsWide: Int(size.width * scale), pixelsHigh: Int(size.height * scale),
            bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { return nil }
        rep.size = size
        guard let ctx = NSGraphicsContext(bitmapImageRep: rep) else { return nil }
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = ctx
        let bounds = NSRect(origin: .zero, size: size)
        NSColor.clear.setFill(); bounds.fill()
        NSBezierPath(roundedRect: bounds, xRadius: 10, yRadius: 10).addClip()
        appearance.performAsCurrentDrawingAppearance {
            NativeChrome.background.setFill(); bounds.fill()
        }
        snapshot.draw(in: bounds)
        for type in NativeChrome.buttonTypes {
            guard let b = window.standardWindowButton(type),
                  let br = b.bitmapImageRepForCachingDisplay(in: b.bounds) else { continue }
            b.cacheDisplay(in: b.bounds, to: br)
            br.draw(in: b.convert(b.bounds, to: nil), from: .zero, operation: .sourceOver, fraction: 1,
                    respectFlipped: true, hints: nil)
        }
        NSGraphicsContext.restoreGraphicsState()
        return rep.representation(using: .png, properties: [:])
    }

    private func finish(error: String?) {
        guard !finished else { return }
        finished = true
        if let error { report["error"] = error }
        report["shots"] = shots
        report["host_calls"] = calls
        report["window_on_any_screen_at_end"] = app.mainWindow.map { w in
            NSScreen.screens.contains { $0.frame.intersects(w.frame) } } ?? false
        let pngs = ["light", "dark"].allSatisfy { ((shots[$0] as? [String: Any])?["path"]) != nil }
        let chromeOK = ["light", "dark"].allSatisfy {
            (((shots[$0] as? [String: Any])?["chrome"] as? [String: Any])?["ok"] as? Bool) == true }
        report["ok"] = error == nil && pngs && chromeOK && (report["window_on_any_screen_at_end"] as? Bool) == false
        app.mainWindow?.orderOut(nil)
        if let data = try? JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]) {
            FileHandle.standardOutput.write(data + Data("\n".utf8))
        }
        NSApp.terminate(nil)
    }

    // MARK: recording host (nothing is performed)
    func bridgeShowWindow() { calls.append("window.show") }
    func bridgeHideWindow() { calls.append("window.hide") }
    func bridgeToggleWindow() { calls.append("window.toggle") }
    func bridgeSetPinned(_ pinned: Bool) { calls.append("window.setPinned") }
    func bridgeNotify(title: String, body: String) { calls.append("notify") }
    func bridgeOpenLink(_ url: URL) { calls.append("link.open (recorded)") }
    func bridgeReveal(_ url: URL) { calls.append("file.reveal (recorded)") }
    func bridgeAppInfo() -> [String: Any] { calls.append("app.info"); return ShellEnvironment.appInfo(app.start) }
    func bridgeStackStatus(_ done: @escaping ([String: Any]) -> Void) {
        calls.append("stack.status"); done(["state": "snapshot", "mode": "snapshot"])
    }
    func bridgeStackStart(done: @escaping BridgeDone) { calls.append("stack.start refused"); done(nil, "snapshot_mode") }
    func bridgeStackStop(done: @escaping BridgeDone) { calls.append("stack.stop refused"); done(nil, "snapshot_mode") }
    func bridgeLoginItemStatus() -> String { calls.append("launchAtLogin.get"); return ShellEnvironment.loginItemStatus() }
    func bridgeSetLoginItem(_ enabled: Bool) throws -> String { calls.append("launchAtLogin.set refused"); return ShellEnvironment.loginItemStatus() }
    func bridgeVoiceStatus() -> [String: Any] { calls.append("voice.status"); return ["available": false] }
    func bridgeMicStart(mode: String, done: @escaping BridgeDone) { calls.append("mic.start refused"); done(nil, "snapshot_mode") }
    func bridgeMicStop(done: @escaping BridgeDone) { calls.append("mic.stop"); done(nil, "snapshot_mode") }
    func bridgeTTSSpeak(text: String, voice: String?, done: @escaping BridgeDone) { calls.append("tts.speak refused"); done(nil, "snapshot_mode") }
    func bridgeTTSStop() { calls.append("tts.stop") }
    func bridgeOpenFile(_ url: URL) { calls.append("file.open (recorded)") }
    func bridgeCopy(_ text: String) { calls.append("copy (recorded)") }
    func bridgeMicStatus() -> [String: Any] { calls.append("mic.status"); return ["permission": "not_requested"] }
    func bridgeTTSStatus() -> [String: Any] { calls.append("tts.status"); return ["available": false] }
    func bridgePickFiles(_ options: FilePickOptions, done: @escaping BridgeDone) { calls.append("files.pick (cancelled)"); done(["files": []], nil) }
}
