// DroidMenuController.swift — Droid section in the Jaeger menu-bar item.
//
// The droid itself stays in Jaeger Droid.app (DroidHost), which holds the
// camera and microphone permissions and keeps the Python service running,
// without its own menu-bar icon. This controller reads
// ~/.jaeger/run/droid/status.json and posts actions to the droid's owner-only
// unix socket, the same way Stream Deck keys already do.

import AppKit
import Darwin

final class DroidMenuController: NSObject {
    private let stateLine = NSMenuItem(title: "Droid: …", action: nil, keyEquivalent: "")
    private let heardLine = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private let senseLine = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private let toggleItem = NSMenuItem(title: "Wake Droid", action: #selector(toggle), keyEquivalent: "")
    private let muteItem = NSMenuItem(title: "Mute Microphone", action: #selector(mute), keyEquivalent: "")
    private let lookItem = NSMenuItem(title: "Look Around", action: #selector(lookAround), keyEquivalent: "")
    private let stopItem = NSMenuItem(title: "Stop Talking", action: #selector(stopTalking), keyEquivalent: "")
    private let viewItem = NSMenuItem(title: "Open Droid View", action: #selector(openDroidView), keyEquivalent: "")
    private let micPermission = NSMenuItem(title: "Microphone: …", action: #selector(openMicSettings), keyEquivalent: "")
    private let cameraPermission = NSMenuItem(title: "Camera: …", action: #selector(openCameraSettings), keyEquivalent: "")
    private let restartItem = NSMenuItem(title: "Restart Droid Service", action: #selector(restartService), keyEquivalent: "")
    private var timer: Timer?

    private var root: String {
        ProcessInfo.processInfo.environment["JAEGER_STATE_DIR"] ?? (NSHomeDirectory() + "/.jaeger")
    }
    private var socketPath: String { root + "/run/droid/control.sock" }

    func install(in menu: NSMenu) {
        stateLine.isEnabled = false
        heardLine.isEnabled = false
        heardLine.isHidden = true
        senseLine.isEnabled = false
        senseLine.isHidden = true
        for entry in [toggleItem, muteItem, lookItem, stopItem, viewItem, micPermission, cameraPermission, restartItem] {
            entry.target = self
        }
        let permissions = NSMenu()
        permissions.addItem(micPermission)
        permissions.addItem(cameraPermission)
        let permissionsItem = NSMenuItem(title: "Permissions", action: nil, keyEquivalent: "")
        permissionsItem.submenu = permissions
        for entry in [stateLine, senseLine, heardLine, toggleItem, muteItem, lookItem, stopItem, viewItem, permissionsItem, restartItem] {
            menu.addItem(entry)
        }
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            self?.refresh()
        }
        timer?.tolerance = 0.25
    }

    func refresh() {
        refreshPermissions()
        let path = root + "/run/droid/status.json"
        guard let data = FileManager.default.contents(atPath: path),
              let status = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            stateLine.title = hostRunning() ? "Droid: service starting…" : "Droid: not running"
            heardLine.isHidden = true
            senseLine.isHidden = true
            toggleItem.isEnabled = false
            muteItem.isEnabled = false
            lookItem.isEnabled = false
            stopItem.isEnabled = false
            return
        }
        let state = status["state"] as? String ?? "off"
        let awake = status["awake"] as? Bool ?? false
        let muted = status["muted"] as? Bool ?? false
        let labels = ["off": "Standby", "waking": "Waking…", "listening": "Listening", "hearing": "Hearing you",
                      "thinking": "Thinking", "speaking": "Speaking", "sleeping": "Going to standby",
                      "present": "Present", "error": "Needs attention"]
        var line = "Droid: " + (labels[state] ?? state)
        if muted { line += " (mic muted)" }
        if let note = status["audio_note"] as? String, !note.isEmpty, state != "error" {
            line += " — " + String(note.prefix(80))
        }
        if state == "error", let error = status["error"] as? String { line += " — " + String(error.prefix(80)) }
        stateLine.title = line
        let heard = (status["heard"] as? String ?? "").trimmingCharacters(in: .whitespaces)
        heardLine.isHidden = !awake || heard.isEmpty
        heardLine.title = "“" + String(heard.prefix(70)) + "”"
        toggleItem.title = awake ? "Put Droid to Sleep" : "Wake Droid"
        toggleItem.isEnabled = true
        muteItem.title = muted ? "Unmute Microphone" : "Mute Microphone"
        muteItem.isEnabled = awake
        lookItem.isEnabled = awake && (status["camera"] as? String) == "live"
        stopItem.isEnabled = awake
        var sense: [String] = []
        switch status["camera"] as? String ?? "off" {
        case "live":
            let faces = status["faces"] as? Int ?? 0
            sense.append(faces > 1 ? "Eyes open · \(faces) people in view" : faces == 1 ? "Eyes open · someone in view" : "Eyes open")
        case "needs permission": sense.append("Eyes closed · camera permission needed")
        case "error": sense.append("Eyes unavailable")
        default: break
        }
        if let action = status["action"] as? String, !action.isEmpty { sense.append(String(action.prefix(50))) }
        if let approval = status["pending_approval"] as? String, !approval.isEmpty { sense = ["Waiting for your yes or no"] }
        senseLine.isHidden = !awake || sense.isEmpty
        senseLine.title = sense.joined(separator: " — ")
    }

    private func refreshPermissions() {
        let path = root + "/run/droid/permissions.json"
        let words = ["authorized": "Allowed", "denied": "Denied — click to open Settings",
                     "notDetermined": "Not asked yet", "restricted": "Restricted"]
        var now: [String: String] = [:]
        if let data = FileManager.default.contents(atPath: path),
           let parsed = (try? JSONSerialization.jsonObject(with: data)) as? [String: String] {
            now = parsed
        }
        func title(_ key: String, _ label: String) -> String {
            guard let value = now[key] else { return "\(label): unknown" }
            return "\(label): " + (words[value] ?? value)
        }
        micPermission.title = title("microphone", "Microphone")
        cameraPermission.title = title("camera", "Camera")
        micPermission.state = now["microphone"] == "authorized" ? .on : .off
        cameraPermission.state = now["camera"] == "authorized" ? .on : .off
    }

    private func control(_ action: String, body: String = "{}") {
        let curl = Process()
        curl.executableURL = URL(fileURLWithPath: "/usr/bin/curl")
        curl.arguments = ["-s", "-m", "5", "--unix-socket", socketPath, "-X", "POST",
                          "-H", "Content-Type: application/json", "-d", body, "http://droid/" + action]
        curl.standardOutput = FileHandle.nullDevice
        curl.standardError = FileHandle.nullDevice
        try? curl.run()
    }

    @objc private func toggle() { control("toggle") }
    @objc private func mute() { control("mute") }
    @objc private func stopTalking() { control("stop") }
    @objc private func lookAround() { control("look", body: "{\"around\":true}") }
    @objc private func openDroidView() {
        if let url = URL(string: "http://127.0.0.1:8790/machine?section=droid") { NSWorkspace.shared.open(url) }
    }
    @objc private func openMicSettings() { openPrivacy("Privacy_Microphone") }
    @objc private func openCameraSettings() { openPrivacy("Privacy_Camera") }
    private func openPrivacy(_ pane: String) {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?" + pane) { NSWorkspace.shared.open(url) }
    }

    @objc private func restartService() {
        if hostRunning() {
            let pkill = Process()
            pkill.executableURL = URL(fileURLWithPath: "/usr/bin/pkill")
            pkill.arguments = ["-TERM", "-f", "jaeger_ai.features.droid.service"]
            pkill.standardOutput = FileHandle.nullDevice
            pkill.standardError = FileHandle.nullDevice
            try? pkill.run()
            return
        }
        let uid = getuid()
        let kick = Process()
        kick.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        kick.arguments = ["kickstart", "gui/\(uid)/com.jenkinsrobotics.jaeger-droid"]
        kick.standardOutput = FileHandle.nullDevice
        kick.standardError = FileHandle.nullDevice
        try? kick.run()
    }

    private func hostRunning() -> Bool {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/pgrep")
        process.arguments = ["-x", "DroidHost"]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            process.waitUntilExit()
            return process.terminationStatus == 0
        } catch {
            return false
        }
    }
}
