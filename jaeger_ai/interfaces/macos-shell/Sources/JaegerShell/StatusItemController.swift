// StatusItemController.swift — JaegerShell menu-bar item (Jaeger original; the running/off icon pair
// follows jaeger_ai/interfaces/swift/Sources/JaegerAI/JaegerAIApp.swift:116-150, adapted to NSStatusItem).
//
// Left click toggles the shell window; right click (or ⌃-click) opens the menu.
// The menu probes the loopback WebUI and gateway only when it opens (and once after a normal launch,
// never in --verify-launch). "Start Jaeger stack…" runs `<launcher> stack up --json` only after the user
// confirms a sheet. Launch at Login is opt-in through SMAppService.mainApp and never changed automatically.

import AppKit
import JaegerShellCore
import ServiceManagement

final class StatusItemController: NSObject, NSMenuDelegate {
    private unowned let app: JaegerShellApplication
    let statusItem: NSStatusItem
    private let menu = NSMenu()
    private let webUIItem = NSMenuItem(title: "WebUI: …", action: nil, keyEquivalent: "")
    private let gatewayItem = NSMenuItem(title: "Gateway: …", action: nil, keyEquivalent: "")
    private let loginItem = NSMenuItem(title: "Launch at Login", action: nil, keyEquivalent: "")
    private var stackRunning = false
    private let runningIcon = StatusItemController.loadIcon("jaeger_icon_22")
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

    private func setRunning(_ running: Bool) {
        if let icon = running ? runningIcon : offIcon { statusItem.button?.image = icon }
        statusItem.button?.toolTip = running ? "Jaeger (ui-rebuild)" : "Jaeger (ui-rebuild) — WebUI not running"
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
        probe(webUIItem, "WebUI", app.start.origin.string + "/")
        probe(gatewayItem, "Gateway", ShellEnvironment.gateway().origin.string + "/health")
    }

    private func probe(_ item: NSMenuItem, _ name: String, _ urlString: String) {
        item.title = "\(name): checking…"
        let url = URL(string: urlString)
        ShellEnvironment.probe(urlString) { [weak self] text in
            item.title = "\(name): \(text.replacingOccurrences(of: "_", with: " ")) (\(url?.host ?? ""):\(url?.port ?? 0))"
            shellLog("[shell][status] \(name.lowercased()) \(text)")
            if name == "WebUI" { self?.setRunning(text == "running") }
        }
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

    @objc private func startStack(_ sender: Any?) {
        let launcher = ShellEnvironment.launcherPath()
        let alert = NSAlert()
        alert.messageText = "Start the Jaeger stack?"
        if let launcher {
            alert.informativeText = "This runs:\n\(launcher) \(StackCLI.upArguments.joined(separator: " "))\n\nIt starts the Jaeger services the same way the CLI does."
            alert.addButton(withTitle: "Start")
            alert.addButton(withTitle: "Cancel")
        } else {
            alert.informativeText = "No jaeger launcher was found (set JaegerLauncher in Info.plist or install the CLI)."
            alert.addButton(withTitle: "OK")
        }
        let run: (NSApplication.ModalResponse) -> Void = { [weak self] response in
            guard let self, let launcher, response == .alertFirstButtonReturn else {
                shellLog("[shell][stack] start cancelled")
                return
            }
            self.runStackUp(launcher)
        }
        app.showWindow()
        if let window = app.mainWindow { alert.beginSheetModal(for: window, completionHandler: run) } else { run(alert.runModal()) }
    }

    private func runStackUp(_ launcher: String) {
        guard !stackRunning else { return }
        stackRunning = true
        shellLog("[shell][stack] started \(launcher) \(StackCLI.upArguments.joined(separator: " "))")
        StackRunner.run(launcher: launcher, arguments: StackCLI.upArguments) { [weak self] data, stderr, status in
            let summary = (try? StackCLI.decodeAction(data)).map(StackCLI.summary) ?? "undecodable reply"
            shellLog("[shell][stack] stack up exited \(status): \(summary)\(stderr.isEmpty ? "" : " stderr=\(stderr.suffix(300))")")
            self?.stackRunning = false
            self?.app.reloadShell(nil)
            self?.refreshIcon()
        }
    }
}
