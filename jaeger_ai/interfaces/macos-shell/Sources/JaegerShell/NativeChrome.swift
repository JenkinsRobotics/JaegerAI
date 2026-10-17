// Native window chrome for the new UI (Jenkins Robotics, 2026-10-17, original). StudioWindowChrome
// (AetherStudio-derived) is unchanged; this runs after its attach(): an empty unified toolbar insets the
// traffic lights, a sidebar NSVisualEffectView sits behind a transparent WKWebView, and the measured
// titlebar height / traffic-light width are injected for the page (NativeChromeContract).
import AppKit
import JaegerShellCore
import WebKit

enum NativeChrome {
    struct Metrics { let titlebarHeight: Double; let trafficLightWidth: Double }

    static func apply(to window: NSWindow, webView: WKWebView) {
        let toolbar = NSToolbar(identifier: "JaegerShellMainToolbar")
        toolbar.displayMode = .iconOnly
        window.toolbar = toolbar
        window.toolbarStyle = .unified
        window.titlebarSeparatorStyle = .none
        window.minSize = NSSize(width: NativeChromeContract.minWidth, height: NativeChromeContract.minHeight)

        let size = window.contentRect(forFrameRect: window.frame).size
        let effect = NSVisualEffectView(frame: NSRect(origin: .zero, size: size))
        effect.material = .sidebar
        effect.blendingMode = .behindWindow
        effect.state = .followsWindowActiveState
        effect.autoresizingMask = [.width, .height]

        if webView.responds(to: NSSelectorFromString("setDrawsBackground:")) {
            webView.setValue(false, forKey: "drawsBackground")
        }
        webView.underPageBackgroundColor = .clear
        webView.frame = effect.bounds
        webView.autoresizingMask = [.width, .height]
        effect.addSubview(webView)
        window.contentView = effect
    }

    static func metrics(_ window: NSWindow) -> Metrics {
        if window.styleMask.contains(.fullScreen) { return Metrics(titlebarHeight: 0, trafficLightWidth: 0) }
        let titlebar = max(0, window.frame.height - window.contentLayoutRect.height)
        let zoom = window.standardWindowButton(.zoomButton)
        let width = zoom.map { $0.convert($0.bounds, to: nil).maxX } ?? 0
        return Metrics(titlebarHeight: Double(titlebar), trafficLightWidth: Double(width))
    }

    static func script(_ m: Metrics) -> String {
        NativeChromeContract.script(titlebarHeight: m.titlebarHeight, trafficLightWidth: m.trafficLightWidth)
    }

    static func installUserScript(_ m: Metrics, in webView: WKWebView) {
        webView.configuration.userContentController.addUserScript(
            WKUserScript(source: script(m), injectionTime: .atDocumentStart, forMainFrameOnly: true))
    }
}
