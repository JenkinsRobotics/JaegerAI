// Jaeger Droid: headless host for Droid mode.
//
// Holds the macOS microphone and camera permissions for the droid and keeps
// the Python droid service (jaeger_ai.features.droid.service) running. The
// Jaeger menu-bar app shows Droid controls and status; Stream Deck keys and
// the WebUI talk to the service over its owner-only unix socket. This app
// never handles audio itself and does not show its own menu-bar icon.
import AppKit
import AVFoundation

final class DroidHost: NSObject, NSApplicationDelegate {
    private var service: Process?
    private var ticks = 0
    private var lastPermissions: [String: String] = [:]
    private var stopping = false

    private var root: String {
        ProcessInfo.processInfo.environment["JAEGER_STATE_DIR"] ?? (NSHomeDirectory() + "/.jaeger")
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        request(.audio) { [weak self] in self?.request(.video) { self?.reportPermissions() } }
        reportPermissions()
        startService()
        Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            self?.ticks += 1
            if (self?.ticks ?? 0) % 3 == 0 { self?.reportPermissions() }
        }
    }

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
