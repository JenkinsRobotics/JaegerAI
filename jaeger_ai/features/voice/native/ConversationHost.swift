import AppKit
import AVFoundation

final class ConversationHost: NSObject, NSApplicationDelegate {
    private var service: Process?

    func applicationDidFinishLaunching(_ notification: Notification) {
        reportPermissions()
        startService()
        request(.audio) { [weak self] in
            self?.reportPermissions()
            self?.request(.video) { self?.reportPermissions() }
        }
    }

    private func reportPermissions() {
        guard let root = ProcessInfo.processInfo.environment["JAEGER_STATE_DIR"] else { return }
        func status(_ media: AVMediaType) -> String {
            switch AVCaptureDevice.authorizationStatus(for: media) {
            case .authorized: return "authorized"
            case .denied: return "denied"
            case .restricted: return "restricted"
            case .notDetermined: return "notDetermined"
            @unknown default: return "unknown"
            }
        }
        let destination = URL(fileURLWithPath: root).appendingPathComponent("conversation-permissions.json")
        do {
            let data = try JSONSerialization.data(withJSONObject: ["microphone": status(.audio), "camera": status(.video)])
            try data.write(to: destination, options: .atomic)
        } catch {
            NSLog("Could not report capture permissions: %@", error.localizedDescription)
        }
    }

    private func request(_ media: AVMediaType, completion: @escaping () -> Void) {
        if AVCaptureDevice.authorizationStatus(for: media) == .notDetermined {
            AVCaptureDevice.requestAccess(for: media) { _ in
                DispatchQueue.main.async(execute: completion)
            }
        } else {
            completion()
        }
    }

    private func startService() {
        guard let python = Bundle.main.object(forInfoDictionaryKey: "JaegerPython") as? String,
              let source = Bundle.main.object(forInfoDictionaryKey: "JaegerSource") as? String else {
            NSApp.terminate(nil)
            return
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.currentDirectoryURL = URL(fileURLWithPath: source)
        process.arguments = ["-B", "-m", "jaeger_ai.features.voice.control", "serve"]
        process.terminationHandler = { _ in DispatchQueue.main.async { NSApp.terminate(nil) } }
        do {
            try process.run()
            service = process
        } catch {
            NSLog("Conversation service failed to start: %@", error.localizedDescription)
            NSApp.terminate(nil)
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let service, service.isRunning { service.terminate() }
    }
}

let application = NSApplication.shared
let delegate = ConversationHost()
application.delegate = delegate
application.setActivationPolicy(.accessory)
application.run()
