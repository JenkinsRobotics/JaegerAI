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
        for entry in [toggleItem, muteItem] { entry.target = self }
        let stopItem = NSMenuItem(title: "Stop Talking", action: #selector(stopTalking), keyEquivalent: "")
        stopItem.target = self
        let openItem = NSMenuItem(title: "Open Jaeger", action: #selector(openJaeger), keyEquivalent: "")
        openItem.target = self
        let restartItem = NSMenuItem(title: "Restart Droid Service", action: #selector(restartService), keyEquivalent: "")
        restartItem.target = self
        for entry in [stateLine, heardLine, .separator(), toggleItem, muteItem, stopItem, .separator(), openItem, restartItem] {
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
        default: symbol = "circle.circle"
        }
        let image = NSImage(systemSymbolName: symbol, accessibilityDescription: "Jaeger Droid: \(state)")
        image?.isTemplate = true
        item.button?.image = image
        item.button?.toolTip = "Jaeger Droid: \(state)"
    }

    private func refresh() {
        let path = root + "/run/droid/status.json"
        guard let data = FileManager.default.contents(atPath: path),
              let status = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            stateLine.title = "Droid: service starting…"
            return
        }
        let state = status["state"] as? String ?? "off"
        let awake = status["awake"] as? Bool ?? false
        let muted = status["muted"] as? Bool ?? false
        if state != lastState { setIcon(state); lastState = state }
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
    }

    private func control(_ action: String) {
        let curl = Process()
        curl.executableURL = URL(fileURLWithPath: "/usr/bin/curl")
        curl.arguments = ["-s", "-m", "5", "--unix-socket", socketPath, "-X", "POST", "http://droid/" + action]
        curl.standardOutput = FileHandle.nullDevice
        curl.standardError = FileHandle.nullDevice
        try? curl.run()
    }

    @objc private func toggle() { control("toggle") }
    @objc private func mute() { control("mute") }
    @objc private func stopTalking() { control("stop") }
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
        let destination = URL(fileURLWithPath: root).appendingPathComponent("run/droid/permissions.json")
        try? FileManager.default.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
        if let data = try? JSONSerialization.data(withJSONObject: ["microphone": status(.audio), "camera": status(.video)]) {
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
