// StatusItemController.swift — JaegerShell menu-bar item (Jaeger original; the running/off icon pair
// follows jaeger_ai/interfaces/swift/Sources/JaegerAI/JaegerAIApp.swift:116-150, adapted to NSStatusItem).
//
// Left click toggles the shell window; right click (or ⌃-click) opens the menu.
// The menu probes the loopback WebUI and gateway only when it opens (and once after a normal launch,
// never in --verify-launch). "Start/Stop Jaeger stack…" go through StackController after a confirm sheet
// (dev mode: own child processes; production: `<launcher> stack up|down --json`). Launch at Login is opt-in through SMAppService.mainApp and never changed automatically.

import AppKit
import JaegerShellCore
import ServiceManagement

final class StatusItemController: NSObject, NSMenuDelegate {
    private unowned let app: JaegerShellApplication
    let statusItem: NSStatusItem
    private let menu = NSMenu()
    private let webUIItem = NSMenuItem(title: "Main screen: …", action: nil, keyEquivalent: "")
    private let gatewayItem = NSMenuItem(title: "Gateway: …", action: nil, keyEquivalent: "")
    private let loginItem = NSMenuItem(title: "Launch at Login", action: nil, keyEquivalent: "")
    private let runningIcon = StatusItemController.loadIcon("jaeger_icon_22")
    private var lastRunning = true
    private var activityBadge: ActivityBadgeState = .off
    private let offIcon = StatusItemController.loadIcon("jaeger_icon_off_22")

    init(app: JaegerShellApplication) {
        self.app = app
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        super.init()
        if let button = statusItem.button {
            button.image = runningIcon
                ?? NSImage(systemSymbolName: "circle.hexagongrid", accessibilityDescription: "Jaeger")
            button.toolTip = "Jaeger (ui-rebuild)"
            button.target = self
            button.action = #selector(clicked(_:))
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
        buildMenu()
    }

    /// PNGs ship at 44×44 (22pt @2x); sized to 18×18 like the old app.
    private static func loadIcon(_ name: String) -> NSImage? {
        guard let image = Bundle.main.image(forResource: name) else { return nil }
        image.size = NSSize(width: 18, height: 18)
        return image
    }

    var isPresent: Bool { statusItem.button != nil && statusItem.isVisible }

    var activityBadgeState: String { activityBadge.rawValue }

    func setActivityBadge(_ state: ActivityBadgeState) {
        activityBadge = state
        renderStatusIcon()
    }

    private func setRunning(_ running: Bool) {
        lastRunning = running
        renderStatusIcon()
    }

    private func renderStatusIcon() {
        let base = (lastRunning ? runningIcon : offIcon)
            ?? NSImage(systemSymbolName: "circle.hexagongrid", accessibilityDescription: "Jaeger")
        if let base, activityBadge == .present || activityBadge == .unknown {
            let state = activityBadge
            statusItem.button?.image = NSImage(size: NSSize(width: 18, height: 18), flipped: false) { rect in
                base.draw(in: rect)
                let dot = NSBezierPath(ovalIn: NSRect(x: 12, y: 0, width: 5, height: 5))
                if state == .present { NSColor.controlAccentColor.setFill(); dot.fill() }
                else { NSColor.secondaryLabelColor.setStroke(); dot.lineWidth = 1; dot.stroke() }
                return true
            }
        } else { statusItem.button?.image = base }
        let suffix = activityBadge == .present ? " — unread retained activity" : activityBadge == .unknown ? " — unread activity unknown" : ""
        statusItem.button?.toolTip = "Jaeger" + (lastRunning ? "" : " — WebUI not running") + suffix
        statusItem.button?.setAccessibilityLabel("Jaeger" + suffix)
    }

    /// One read-only probe of the WebUI to pick the icon (normal launch only).
    func refreshIcon() {
        ShellEnvironment.probe(app.start.origin.string + "/") { [weak self] text in self?.setRunning(text == "running") }
    }

    private func add(_ title: String, _ action: Selector?, _ key: String = "") -> NSMenuItem {
        let item = menu.addItem(withTitle: title, action: action, keyEquivalent: key)
        item.target = self
        return item
    }

    private func buildMenu() {
        menu.delegate = self
        menu.autoenablesItems = false
        _ = add("Show / Hide Jaeger", #selector(toggle(_:)))
        menu.addItem(.separator())
        webUIItem.isEnabled = false; menu.addItem(webUIItem)
        gatewayItem.isEnabled = false; menu.addItem(gatewayItem)
        _ = add("Start Jaeger stack…", #selector(startStack(_:)))
        _ = add("Stop Jaeger stack…", #selector(stopStack(_:)))
        menu.addItem(.separator())
        loginItem.target = self; loginItem.action = #selector(toggleLoginItem(_:)); menu.addItem(loginItem)
        _ = add("Reload", #selector(reload(_:)))
        _ = add("Open in Browser", #selector(openInBrowser(_:)))
        menu.addItem(.separator())
        _ = add("Quit Jaeger Shell", #selector(quit(_:)))
    }

    @objc private func clicked(_ sender: Any?) {
        let event = NSApp.currentEvent
        if event?.type == .rightMouseUp || event?.modifierFlags.contains(.control) == true {
            statusItem.menu = menu
            statusItem.button?.performClick(nil)
            statusItem.menu = nil
        } else {
            app.toggleWindow()
        }
    }

    // MARK: menu

    func menuWillOpen(_ menu: NSMenu) {
        loginItem.state = SMAppService.mainApp.status == .enabled ? .on : .off
        probe(webUIItem, "Main screen", app.start.origin.string + "/")
        probe(gatewayItem, "Gateway", ShellEnvironment.gateway().origin.string + "/health")
    }

    private func probe(_ item: NSMenuItem, _ name: String, _ urlString: String) {
        item.title = "\(name): checking…"
        let url = URL(string: urlString)
        ShellEnvironment.probe(urlString) { [weak self] text in
            item.title = "\(name): \(text.replacingOccurrences(of: "_", with: " ")) (\(url?.host ?? ""):\(url?.port ?? 0))"
            shellLog("[shell][status] \(name.lowercased()) \(text)")
            if name == "Main screen" { self?.setRunning(text == "running") }
        }
    }

    // MARK: --visible-check hooks (read-only: titles/icon; probe = what opening the menu does)
    func debugProbe() { menuWillOpen(menu) }
    func debugSnapshot() -> [String: Any] {
        let image = statusItem.button?.image
        let icon = image == nil ? "none" : (image === runningIcon ? "running" : (image === offIcon ? "off" : "fallback"))
        return ["present": isPresent, "icon": icon, "titles": menu.items.filter { !$0.isSeparatorItem }.map(\.title)]
    }

    @objc private func toggle(_ sender: Any?) { app.toggleWindow() }
    @objc private func reload(_ sender: Any?) { app.showWindow(); app.reloadShell(nil) }
    @objc private func quit(_ sender: Any?) { NSApp.terminate(nil) }

    @objc private func openInBrowser(_ sender: Any?) {
        if let url = URL(string: app.start.origin.string + "/") { NSWorkspace.shared.open(url) }
    }

    @objc private func toggleLoginItem(_ sender: Any?) {
        do {
            let status = try ShellEnvironment.setLoginItem(SMAppService.mainApp.status != .enabled)
            shellLog("[shell][login] status now \(status)")
        } catch {
            shellLog("[shell][login] change failed: \(error.localizedDescription)")
            NSAlert(error: error).runModal()
        }
    }

    @objc private func startStack(_ sender: Any?) { runStack(.start) }
    @objc private func stopStack(_ sender: Any?) { runStack(.stop) }

    /// Confirm sheet, then StackController (dev: own children; production: `jaeger stack up|down --json`).
    private func runStack(_ action: StackController.Action) {
        app.stack.confirmThen(action) { [weak self] in
            guard let self else { return }
            let finish: BridgeDone = { [weak self] result, error in
                shellLog("[shell][stack] \(action.rawValue) → \(error ?? "ok \(result?["mode"] ?? "")")")
                self?.app.reloadShell(nil)
                self?.refreshIcon()
            }
            action == .start ? self.app.stack.start(done: finish) : self.app.stack.stop(done: finish)
        }
    }
}
