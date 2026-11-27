// StackRunner.swift — runs `jaeger stack … --json` for the confirm-gated Start menu item.
// Ported (adapted) from jaeger_ai/interfaces/swift/Sources/JaegerAI/Bridge/StackManager.swift:75-101
// (`runStackCommand`, Jenkins Robotics). Changes: callback instead of async/Task.detached; stderr read
// concurrently (avoids a full-pipe stall); launcher passed in (LauncherResolver) instead of
// BridgeProcess.jaegerPath(); same 120 s watchdog and null stdin.

import Foundation

enum StackRunner {
    static func run(launcher: String, arguments: [String], timeout: TimeInterval = 120,
                    done: @escaping (_ stdout: Data, _ stderr: String, _ status: Int32) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            let out = Pipe()
            let err = Pipe()
            process.executableURL = URL(fileURLWithPath: launcher)
            process.arguments = arguments
            process.standardInput = FileHandle.nullDevice
            process.standardOutput = out
            process.standardError = err
            do { try process.run() } catch {
                DispatchQueue.main.async { done(Data(), error.localizedDescription, -1) }
                return
            }
            let watchdog = DispatchWorkItem { if process.isRunning { process.terminate() } }
            DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: watchdog)
            var errData = Data()
            let group = DispatchGroup()
            group.enter()
            DispatchQueue.global().async { errData = err.fileHandleForReading.readDataToEndOfFile(); group.leave() }
            let data = out.fileHandleForReading.readDataToEndOfFile()
            group.wait()
            process.waitUntilExit()
            watchdog.cancel()
            let stderr = String(decoding: errData, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
            DispatchQueue.main.async { done(data, stderr, process.terminationStatus) }
        }
    }
}
