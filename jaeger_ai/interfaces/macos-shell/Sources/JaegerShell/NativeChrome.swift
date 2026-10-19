// Native window chrome for the main screen (Jenkins Robotics, 2026-10-17, original). StudioWindowChrome
// (AetherStudio-derived) is unchanged; this runs after its attach(). Values: NativeChromeContract (the measured
// Grok Bot window: solid #fcfcfc / #121212, no vibrancy, 52 pt band, traffic lights at x16 / y15, 600×520 min).
// The WKWebView is the window's content view under a transparent 32 pt titlebar (no toolbar: a unified toolbar
// makes AppKit clamp the minimum height to ~544 and the target has none); the 52 pt band is the page's, and the
// traffic lights are moved into it. Band height + traffic-light reserve are injected for the page.
import AppKit
import JaegerShellCore
import WebKit

enum NativeChrome {
    struct Metrics {
        let titlebarHeight: Double, trafficLightWidth: Double, bandHeight: Double, trafficLightReserve: Double
    }

    static func isDark(_ appearance: NSAppearance) -> Bool {
        appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
    }

    static func color(_ rgb: NativeChromeContract.RGB) -> NSColor {
        NSColor(srgbRed: CGFloat(rgb.r) / 255, green: CGFloat(rgb.g) / 255, blue: CGFloat(rgb.b) / 255, alpha: 1)
    }

    /// Solid window background that follows the effective appearance.
    static let background = NSColor(name: NSColor.Name("JaegerChromeBackground")) { appearance in
        color(NativeChromeContract.background(dark: isDark(appearance)))
    }

    static let buttonTypes: [NSWindow.ButtonType] = [.closeButton, .miniaturizeButton, .zoomButton]

    static func apply(to window: NSWindow, webView: WKWebView) {
        window.toolbar = nil
        window.titlebarSeparatorStyle = .none
        // After StudioWindowChrome.attach (900×600): the measured target minimum.
        window.minSize = NSSize(width: NativeChromeContract.minWidth, height: NativeChromeContract.minHeight)
        window.isOpaque = true
        window.backgroundColor = background

        // KVC key "drawsBackground" (WebKit implements it as _setDrawsBackground:, so check both selectors
        // before setting — KVC on a missing key raises). The solid window shows until the page paints.
        if webView.responds(to: NSSelectorFromString("_setDrawsBackground:"))
            || webView.responds(to: NSSelectorFromString("setDrawsBackground:")) {
            webView.setValue(false, forKey: "drawsBackground")
        }
        applyAppearance(window, webView: webView)
        webView.autoresizingMask = [.width, .height]
        window.contentView = webView
        layoutTrafficLights(window)
    }

    /// WebKit stores underPageBackgroundColor resolved, so set it again for each appearance.
    static func applyAppearance(_ window: NSWindow, webView: WKWebView) {
        webView.underPageBackgroundColor = color(NativeChromeContract.background(dark: isDark(window.effectiveAppearance)))
    }

    /// Frames of close / minimise / zoom in window coordinates, top-left origin.
    static func trafficLightFrames(_ window: NSWindow) -> [NativeChromeContract.Rect] {
        let h = Double(window.frame.height)
        return buttonTypes.compactMap { window.standardWindowButton($0) }.map { b in
            let r = b.convert(b.bounds, to: nil)
            return NativeChromeContract.Rect(x: Double(r.minX), top: h - Double(r.maxY),
                                             width: Double(r.width), height: Double(r.height))
        }
    }

    /// Puts the traffic lights at the contract inset. AppKit re-lays them out on resize, key changes and
    /// full-screen exit, so the window delegate calls this again then.
    static func layoutTrafficLights(_ window: NSWindow) {
        guard !window.styleMask.contains(.fullScreen) else { return }
        let buttons = buttonTypes.compactMap { window.standardWindowButton($0) }
        guard buttons.count == buttonTypes.count else { return }
        let h = Double(window.frame.height)
        let targets = NativeChromeContract.trafficLightTargets(trafficLightFrames(window))
        for (button, t) in zip(buttons, targets) {
            guard let parent = button.superview else { continue }
            let inWindow = NSRect(x: t.x, y: h - t.top - t.height, width: t.width, height: t.height)
            let local = parent.convert(inWindow, from: nil)
            if button.frame.origin != local.origin { button.setFrameOrigin(local.origin) }
        }
    }

    static func metrics(_ window: NSWindow) -> Metrics {
        if window.styleMask.contains(.fullScreen) {
            return Metrics(titlebarHeight: 0, trafficLightWidth: 0, bandHeight: NativeChromeContract.bandHeight,
                           trafficLightReserve: 0)
        }
        let titlebar = max(0, window.frame.height - window.contentLayoutRect.height)
        let zoomMaxX = trafficLightFrames(window).last?.maxX
        return Metrics(titlebarHeight: Double(titlebar), trafficLightWidth: zoomMaxX ?? 0,
                       bandHeight: NativeChromeContract.bandHeight,
                       trafficLightReserve: NativeChromeContract.trafficLightReserve(zoomMaxX: zoomMaxX))
    }

    static func script(_ m: Metrics) -> String {
        NativeChromeContract.script(titlebarHeight: m.titlebarHeight, trafficLightWidth: m.trafficLightWidth,
                                    bandHeight: m.bandHeight, trafficLightReserve: m.trafficLightReserve)
    }

    static func installUserScript(_ m: Metrics, in webView: WKWebView) {
        webView.configuration.userContentController.addUserScript(
            WKUserScript(source: script(m), injectionTime: .atDocumentStart, forMainFrameOnly: true))
    }

    /// Re-injects the metrics into the live page (full-screen enter/exit).
    static func push(_ window: NSWindow, to webView: WKWebView) {
        webView.evaluateJavaScript(script(metrics(window)), completionHandler: nil)
    }

    static func hex(_ color: NSColor, in appearance: NSAppearance) -> String {
        var out = "?"
        appearance.performAsCurrentDrawingAppearance {
            if let c = color.usingColorSpace(.sRGB) {
                out = NativeChromeContract.RGB(UInt8((c.redComponent * 255).rounded()),
                                               UInt8((c.greenComponent * 255).rounded()),
                                               UInt8((c.blueComponent * 255).rounded())).hex
            }
        }
        return out
    }

    /// What the window actually is, for --verify-launch / --snapshot.
    static func report(_ window: NSWindow, webView: WKWebView?) -> [String: Any] {
        let m = metrics(window)
        let lights = trafficLightFrames(window)
        let aqua = NSAppearance(named: .aqua)!, dark = NSAppearance(named: .darkAqua)!
        let mask = window.styleMask
        var maskNames: [String] = []
        for (flag, name) in [(NSWindow.StyleMask.titled, "titled"), (.closable, "closable"),
                             (.miniaturizable, "miniaturizable"), (.resizable, "resizable"),
                             (.fullSizeContentView, "fullSizeContentView")] where mask.contains(flag) {
            maskNames.append(name)
        }
        // Does a click in the band (right of the traffic lights) reach the page?
        var bandHit = "none"
        var bandHitIsPage = false
        if let frame = window.contentView?.superview {
            let p = NSPoint(x: 300, y: window.frame.height - 26)
            if let hit = frame.hitTest(p) {
                bandHit = String(describing: type(of: hit))
                if let webView { bandHitIsPage = hit === webView || hit.isDescendant(of: webView) }
            }
        }
        let bgLight = hex(background, in: aqua), bgDark = hex(background, in: dark)
        let current = NativeChromeContract.background(dark: isDark(window.effectiveAppearance)).hex
        let under = webView.map { hex($0.underPageBackgroundColor, in: window.effectiveAppearance) } ?? "none"
        let draws = (webView?.value(forKey: "drawsBackground") as? Bool) ?? true
        let first = lights.first
        let size = window.frame.size
        let ok = window.contentView === webView && window.isOpaque && !draws
            && bgLight == NativeChromeContract.backgroundLight.hex && bgDark == NativeChromeContract.backgroundDark.hex
            && window.minSize == NSSize(width: NativeChromeContract.minWidth, height: NativeChromeContract.minHeight)
            && window.titlebarAppearsTransparent && window.titleVisibility == .hidden
            && mask.contains(.fullSizeContentView) && window.toolbar == nil && under == current && bandHitIsPage
            && (mask.contains(.fullScreen) || (first.map { abs($0.x - NativeChromeContract.trafficLightX) < 0.5
                && abs($0.top - NativeChromeContract.trafficLightY) < 0.5 } ?? false))
        return [
            "ok": ok,
            "style_mask": maskNames,
            "title_hidden": window.titleVisibility == .hidden,
            "titlebar_transparent": window.titlebarAppearsTransparent,
            "toolbar": window.toolbar == nil ? "none" : "present",
            "appearance": isDark(window.effectiveAppearance) ? "dark" : "light",
            "window_size": [Double(size.width), Double(size.height)],
            "min_size": [Double(window.minSize.width), Double(window.minSize.height)],
            "content_view": window.contentView.map { String(describing: type(of: $0)) } ?? "none",
            "content_view_is_webview": window.contentView === webView,
            "window_opaque": window.isOpaque,
            "background": ["light": bgLight, "dark": bgDark],
            "webview_draws_background": draws,
            "under_page_background": under,
            "titlebar_height": m.titlebarHeight,
            "band_height": m.bandHeight,
            "traffic_lights": lights.map { [$0.x, $0.top, $0.width, $0.height] },
            "traffic_light_reserve": m.trafficLightReserve,
            "band_hit_test": bandHit,
            "band_click_reaches_page": bandHitIsPage,
            "injected": NativeChromeContract.values(titlebarHeight: m.titlebarHeight,
                                                    trafficLightWidth: m.trafficLightWidth,
                                                    bandHeight: m.bandHeight,
                                                    trafficLightReserve: m.trafficLightReserve),
        ]
    }
}
