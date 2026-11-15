// Jaeger Droid: the menu-bar host for Droid mode.
//
// Holds the macOS microphone and camera permissions for the droid, keeps the
// Python droid service (jaeger_ai.features.droid.service) running, and shows
// the droid's state in the menu bar. Stream Deck keys and the WebUI talk to the
// service over its owner-only unix socket; this app never handles audio itself.
import AppKit
import AVFoundation

final class DroidHost: NSObject, NSApplicationDelegate {
    private var service: Process?
    private var item: NSStatusItem!
    private let menu = NSMenu()
    private let stateLine = NSMenuItem(title: "Droid: starting…", action: nil, keyEquivalent: "")
    private let heardLine = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private let toggleItem = NSMenuItem(title: "Wake Droid", action: #selector(toggle), keyEquivalent: "")
    private let muteItem = NSMenuItem(title: "Mute Microphone", action: #selector(mute), keyEquivalent: "")
    private let senseLine = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private let lookItem = NSMenuItem(title: "Look Around", action: #selector(lookAround), keyEquivalent: "")
    private let micPermission = NSMenuItem(title: "Microphone", action: #selector(openMicSettings), keyEquivalent: "")
    private let cameraPermission = NSMenuItem(title: "Camera", action: #selector(openCameraSettings), keyEquivalent: "")
    private var ticks = 0
    private var lastPermissions: [String: String] = [:]
    private var stopping = false
    private var lastState = ""

    private var root: String {
        ProcessInfo.processInfo.environment["JAEGER_STATE_DIR"] ?? (NSHomeDirectory() + "/.jaeger")
    }
    private var socketPath: String { root + "/run/droid/control.sock" }

    func applicationDidFinishLaunching(_ notification: Notification) {
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        setIcon("off")
        stateLine.isEnabled = false
        heardLine.isEnabled = false
        heardLine.isHidden = true
        senseLine.isEnabled = false
        senseLine.isHidden = true
        for entry in [toggleItem, muteItem, lookItem, micPermission, cameraPermission] { entry.target = self }
        let stopItem = NSMenuItem(title: "Stop Talking", action: #selector(stopTalking), keyEquivalent: "")
        stopItem.target = self
        let openItem = NSMenuItem(title: "Open Jaeger", action: #selector(openJaeger), keyEquivalent: "")
        openItem.target = self
        let viewItem = NSMenuItem(title: "Open Droid View", action: #selector(openDroidView), keyEquivalent: "")
        viewItem.target = self
        let permissions = NSMenu()
        permissions.addItem(micPermission)
        permissions.addItem(cameraPermission)
        let permissionsItem = NSMenuItem(title: "Permissions", action: nil, keyEquivalent: "")
        permissionsItem.submenu = permissions
        let restartItem = NSMenuItem(title: "Restart Droid Service", action: #selector(restartService), keyEquivalent: "")
        restartItem.target = self
        for entry in [stateLine, senseLine, heardLine, .separator(), toggleItem, muteItem, lookItem, stopItem, .separator(),
                      viewItem, openItem, .separator(), permissionsItem, restartItem] {
            menu.addItem(entry)
        }
        item.menu = menu
        request(.audio) { [weak self] in self?.request(.video) { self?.reportPermissions() } }
        reportPermissions()
        startService()
        Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in self?.refresh() }
    }

    private func setIcon(_ state: String) {
        let symbol: String
        switch state {
        case "listening": symbol = "waveform.circle"
        case "hearing": symbol = "ear"
        case "thinking": symbol = "ellipsis.circle"
        case "speaking": symbol = "waveform.circle.fill"
        case "waking", "sleeping": symbol = "circle.dotted"
        case "error": symbol = "exclamationmark.triangle"
        case "muted": symbol = "mic.slash.circle"
        default: symbol = "circle.circle"
        }
        let image = NSImage(systemSymbolName: symbol, accessibilityDescription: "Jaeger Droid: \(state)")
        image?.isTemplate = true
        item.button?.image = image
        item.button?.toolTip = "Jaeger Droid: \(state)"
    }

    private func refresh() {
        ticks += 1
        if ticks % 3 == 0 { reportPermissions() }
        let path = root + "/run/droid/status.json"
        guard let data = FileManager.default.contents(atPath: path),
              let status = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            stateLine.title = "Droid: service starting…"
            return
        }
        let state = status["state"] as? String ?? "off"
        let awake = status["awake"] as? Bool ?? false
        let muted = status["muted"] as? Bool ?? false
        let iconState = awake && muted && state == "listening" ? "muted" : state
        if iconState != lastState { setIcon(iconState); lastState = iconState }
        let labels = ["off": "Standby", "waking": "Waking…", "listening": "Listening", "hearing": "Hearing you",
                      "thinking": "Thinking", "speaking": "Speaking", "sleeping": "Going to standby", "error": "Needs attention"]
        var line = "Droid: " + (labels[state] ?? state)
        if muted { line += " (mic muted)" }
        if state == "error", let error = status["error"] as? String { line += " — " + String(error.prefix(80)) }
        stateLine.title = line
        let heard = (status["heard"] as? String ?? "").trimmingCharacters(in: .whitespaces)
        heardLine.isHidden = !awake || heard.isEmpty
        heardLine.title = "“" + String(heard.prefix(70)) + "”"
        toggleItem.title = awake ? "Put Droid to Sleep" : "Wake Droid"
        muteItem.title = muted ? "Unmute Microphone" : "Mute Microphone"
        muteItem.isEnabled = awake
        lookItem.isEnabled = awake && (status["camera"] as? String) == "live"
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
    @objc private func openJaeger() {
        if let url = URL(string: "http://127.0.0.1:8790/") { NSWorkspace.shared.open(url) }
    }
    @objc private func restartService() { service?.terminate() }

    private func reportPermissions() {
        func status(_ media: AVMediaType) -> String {
            switch AVCaptureDevice.authorizationStatus(for: media) {
            case .authorized: return "authorized"
            case .denied: return "denied"
            case .restricted: return "restricted"
            case .notDetermined: return "notDetermined"
            @unknown default: return "unknown"
            }
        }
        let now = ["microphone": status(.audio), "camera": status(.video)]
        let words = ["authorized": "Allowed", "denied": "Denied — click to open Settings",
                     "notDetermined": "Not asked yet", "restricted": "Restricted"]
        micPermission.title = "Microphone: " + (words[now["microphone"]!] ?? now["microphone"]!)
        cameraPermission.title = "Camera: " + (words[now["camera"]!] ?? now["camera"]!)
        micPermission.state = now["microphone"] == "authorized" ? .on : .off
        cameraPermission.state = now["camera"] == "authorized" ? .on : .off
        if now == lastPermissions { return }
        lastPermissions = now
        let destination = URL(fileURLWithPath: root).appendingPathComponent("run/droid/permissions.json")
        try? FileManager.default.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
        if let data = try? JSONSerialization.data(withJSONObject: now) {
            try? data.write(to: destination, options: .atomic)
        }
    }

    private func request(_ media: AVMediaType, completion: @escaping () -> Void) {
        if AVCaptureDevice.authorizationStatus(for: media) == .notDetermined {
            AVCaptureDevice.requestAccess(for: media) { _ in DispatchQueue.main.async(execute: completion) }
        } else {
            completion()
        }
    }

    private func startService() {
        guard !stopping,
              let python = Bundle.main.object(forInfoDictionaryKey: "JaegerPython") as? String,
              let source = Bundle.main.object(forInfoDictionaryKey: "JaegerSource") as? String else { return }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.currentDirectoryURL = URL(fileURLWithPath: source)
        process.arguments = ["-B", "-m", "jaeger_ai.features.droid.service"]
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = source + ":" + source + "/packages/jaeger-os"
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["JAEGER_STATE_DIR"] = root
        process.environment = env
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) { self?.startService() }
        }
        do {
            try process.run()
            service = process
        } catch {
            NSLog("Droid service failed to start: %@", error.localizedDescription)
            DispatchQueue.main.asyncAfter(deadline: .now() + 10) { [weak self] in self?.startService() }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        stopping = true
        if let service, service.isRunning {
            service.terminate()
            service.waitUntilExit()
        }
    }
}

let application = NSApplication.shared
let delegate = DroidHost()
application.delegate = delegate
application.setActivationPolicy(.accessory)
signal(SIGTERM, SIG_IGN)
let terminate = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
terminate.setEventHandler { NSApp.terminate(nil) }
terminate.resume()
application.run()
