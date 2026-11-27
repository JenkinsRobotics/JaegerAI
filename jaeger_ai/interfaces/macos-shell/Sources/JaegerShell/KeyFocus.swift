// Key-window focus for the main window. The dev shell is LSUIElement/.accessory; on screen, plain keys and
// left clicks never reached the page while ⌘-shortcuts (menu key equivalents) and right-clicks did — the
// signature of a visible window that isn't key / a web view that isn't first responder. On show and on
// activation we activate, make the window key and the web view first responder, and log the result.
import AppKit
import WebKit

enum KeyFocus {
    static func status(_ window: NSWindow?, _ reason: String) -> String {
        guard let window else { return "[key] \(reason) no-window" }
        let first = window.firstResponder.map { String(describing: type(of: $0)) } ?? "nil"
        return "[key] \(reason) key=\(window.isKeyWindow) active=\(NSApp.isActive) canBecomeKey=\(window.canBecomeKey) visible=\(window.isVisible) first=\(first) webMovesWindow=\((window.contentView as? WKWebView)?.mouseDownCanMoveWindow ?? false)"
    }

    @discardableResult
    static func log(_ window: NSWindow?, _ reason: String) -> String {
        let line = status(window, reason)
        shellLog(line)
        return line
    }

    /// Activate (menu-bar app: ignoring other apps, since it has no Dock icon to click), make the window key and
    /// the web view first responder. `activate: false` in headless checks, which must never take focus.
    static func focus(_ window: NSWindow, webView: WKWebView?, activate: Bool, reason: String) {
        if activate { NSApp.activate(ignoringOtherApps: true) }
        window.makeKeyAndOrderFront(nil)
        if let webView, window.firstResponder !== webView { window.makeFirstResponder(webView) }
        log(window, reason)
    }
}
