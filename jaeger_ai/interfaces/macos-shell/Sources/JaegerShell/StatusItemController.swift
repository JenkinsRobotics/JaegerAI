// StatusItemController.swift — JaegerShell menu-bar item (Jaeger original, not derived from AetherStudio).
//
// Left click toggles the shell window; right click (or ⌃-click) opens the menu.
// The menu probes the loopback WebUI and gateway only when it opens. "Start Jaeger
// stack…" runs `<launcher> stack up --json` only after the user confirms a sheet.
// Launch at Login is opt-in through SMAppService.mainApp and is never changed
// automatically.

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
    private var stackProcess: Process?

    init(app: JaegerShellApplication) {
        self.app = app
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        super.init()
        if let button = statusItem.button {
            if let image = Bundle.main.image(forResource: "jaeger_icon_22") {
                image.size = NSSize(width: 18, height: 18)
                button.image = image
            } else {
                button.image = NSImage(systemSymbolName: "circle.hexagongrid", accessibilityDescription: "Jaeger")
            }
            button.toolTip = "Jaeger (ui-rebuild)"
            button.target = self
            button.action = #selector(clicked(_:))
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
        buildMenu()
    }

    var isPresent: Bool { statusItem.button != nil && statusItem.isVisible }

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
        guard let url = URL(string: urlString) else { return }
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 1.5)
        request.httpMethod = "GET"
        URLSession(configuration: .ephemeral).dataTask(with: request) { _, response, error in
            let code = (response as? HTTPURLResponse)?.statusCode
            let text = code.map { (200..<400).contains($0) ? "running" : "HTTP \($0)" } ?? "not running"
            DispatchQueue.main.async {
                item.title = "\(name): \(text) (\(url.host ?? ""):\(url.port ?? 0))"
                shellLog("[shell][status] \(name.lowercased()) \(text)\(error.map { " \($0.localizedDescription)" } ?? "")")
            }
        }.resume()
    }

    @objc private func toggle(_ sender: Any?) { app.toggleWindow() }
    @objc private func reload(_ sender: Any?) { app.showWindow(); app.reloadShell(nil) }
    @objc private func quit(_ sender: Any?) { NSApp.terminate(nil) }

    @objc private func openInBrowser(_ sender: Any?) {
        if let url = URL(string: app.start.origin.string + "/") { NSWorkspace.shared.open(url) }
    }

    @objc private func toggleLoginItem(_ sender: Any?) {
        let service = SMAppService.mainApp
        do {
            if service.status == .enabled {
                try service.unregister()
            } else {
                try service.register()
            }
            shellLog("[shell][login] status now \(ShellEnvironment.loginItemStatus())")
        } catch {
            shellLog("[shell][login] change failed: \(error.localizedDescription)")
            let alert = NSAlert(error: error)
            alert.runModal()
        }
    }

    @objc private func startStack(_ sender: Any?) {
        let launcher = ShellEnvironment.launcherPath()
        let alert = NSAlert()
        alert.messageText = "Start the Jaeger stack?"
        if let launcher {
            alert.informativeText = "This runs:\n\(launcher) stack up --json\n\nIt starts the Jaeger services the same way the CLI does."
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
        guard stackProcess == nil else { return }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: launcher)
        process.arguments = ["stack", "up", "--json"]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        process.terminationHandler = { [weak self] p in
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let tail = String(decoding: data.suffix(400), as: UTF8.self)
            DispatchQueue.main.async {
                shellLog("[shell][stack] stack up exited \(p.terminationStatus): \(tail)")
                self?.stackProcess = nil
                self?.app.reloadShell(nil)
            }
        }
        do {
            try process.run()
            stackProcess = process
            shellLog("[shell][stack] started \(launcher) stack up --json")
        } catch {
            shellLog("[shell][stack] launch failed: \(error.localizedDescription)")
        }
    }
}
