import AppKit
import AVFoundation

final class ConversationHost: NSObject, NSApplicationDelegate {
    private var service: Process?

    func applicationDidFinishLaunching(_ notification: Notification) {
        startService()
        request(.audio) { [weak self] in
            self?.request(.video) {}
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
