// MacControlMenuController.swift — quick Mac actions in the one Jaeger menu.
//
// Same actions the agent's system_control tool exposes (lock_screen,
// display_off, status), so the menu, chat and the phone all do the same thing.
// Lock uses login.framework's SACLockScreenImmediate (what Control Center's
// Lock Screen calls); display off is `pmset displaysleepnow`.

import AppKit
import Darwin

final class MacControlMenuController: NSObject {
    private let lockItem = NSMenuItem(title: "Lock Mac", action: #selector(lockMac), keyEquivalent: "")
    private let displayItem = NSMenuItem(title: "Turn Display Off", action: #selector(displayOff), keyEquivalent: "")
    private let statusItem = NSMenuItem(title: "Mac Status…", action: #selector(showStatus), keyEquivalent: "")

    func install(in menu: NSMenu) {
        let header = NSMenuItem(title: "Mac", action: nil, keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)
        for entry in [lockItem, displayItem, statusItem] {
            entry.target = self
            menu.addItem(entry)
        }
    }

    @objc private func lockMac() {
        typealias LockFn = @convention(c) () -> Int32
        if let handle = dlopen("/System/Library/PrivateFrameworks/login.framework/Versions/Current/login", RTLD_NOW),
           let sym = dlsym(handle, "SACLockScreenImmediate") {
            let fn = unsafeBitCast(sym, to: LockFn.self)
            if fn() == 0 { return }
        }
        run("/usr/bin/pmset", ["displaysleepnow"])
    }

    @objc private func displayOff() {
        run("/usr/bin/pmset", ["displaysleepnow"])
    }

    @objc private func showStatus() {
        var lines: [String] = []
        lines.append(output("/usr/bin/uptime", []).trimmingCharacters(in: .whitespacesAndNewlines))
        let disk = output("/bin/df", ["-h", "/System/Volumes/Data"]).split(separator: "\n")
        if disk.count > 1 {
            let cols = disk[1].split(separator: " ", omittingEmptySubsequences: true)
            if cols.count > 4 { lines.append("Disk: \(cols[3]) free of \(cols[1]) (\(cols[4]) used)") }
        }
        let power = output("/usr/bin/pmset", ["-g", "batt"]).split(separator: "\n").first.map(String.init) ?? ""
        if !power.isEmpty { lines.append(power) }
        let alert = NSAlert()
        alert.messageText = "Mac Status"
        alert.informativeText = lines.joined(separator: "\n")
        NSApp.activate(ignoringOtherApps: true)
        alert.runModal()
    }

    private func run(_ path: String, _ args: [String]) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: path)
        p.arguments = args
        try? p.run()
    }

    private func output(_ path: String, _ args: [String]) -> String {
        let p = Process()
        let pipe = Pipe()
        p.executableURL = URL(fileURLWithPath: path)
        p.arguments = args
        p.standardOutput = pipe
        do { try p.run() } catch { return "" }
        p.waitUntilExit()
        return String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    }
}
