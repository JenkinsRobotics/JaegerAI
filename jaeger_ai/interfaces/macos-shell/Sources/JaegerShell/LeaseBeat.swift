// Ported from jaeger_ai/interfaces/swift/Sources/JaegerAI/Bridge/StackManager.swift:104-181 (LifecycleLeaseBeat),
// Jenkins Robotics, same repository. Changes (2026-10-17): an instance with an explicit path (resolved by
// StackController: the dev stack's isolated state dir, else LeaseContract.path = lifecycle_lease.py's
// state-dir logic) instead of a static enum; beats every 2 s (the contract suspends at 5 s; the old 5 s beat
// grazed it); the temp file is 0600 before the rename, like LifecycleLease.beat; App Nap is held off while
// beating; beat history for the headless check; retire removes the lease by default (no shutdown); the old
// expired-lease retire survives only as the dev-build `.expire` comparison.
import Foundation
import JaegerShellCore

final class LeaseBeat: @unchecked Sendable {
    let path: String
    private let queue = DispatchQueue(label: "ai.jaeger.shell.lifecycle-lease")
    // Touched only on `queue`.
    private var timer: DispatchSourceTimer?
    private var activity: NSObjectProtocol?
    private var history: [Double] = []
    private var lastError: String?

    init(path: String) { self.path = path }

    var isRunning: Bool { queue.sync { timer != nil } }
    var beats: [Double] { queue.sync { history } }

    func start() {
        queue.sync {
            guard timer == nil else { return }
            activity = ProcessInfo.processInfo.beginActivity(
                options: [.userInitiatedAllowingIdleSystemSleep], reason: "Jaeger lifecycle lease heartbeat")
            write(beatAt: nil)
            let source = DispatchSource.makeTimerSource(queue: queue)
            source.schedule(deadline: .now() + LeaseContract.beatInterval, repeating: LeaseContract.beatInterval,
                            leeway: .milliseconds(100))
            source.setEventHandler { [weak self] in self?.write(beatAt: nil) }
            source.resume()
            timer = source
        }
    }

    /// Stop beating and give the lease up (see LeaseRetire).
    func retire(_ mode: LeaseRetire) -> [String: Any] {
        queue.sync {
            timer?.setEventHandler {}
            timer?.cancel()
            timer = nil
            if let activity { ProcessInfo.processInfo.endActivity(activity) }
            activity = nil
            var result: [String: Any] = ["mode": mode.rawValue, "beats": history.count]
            switch mode {
            case .remove:
                do {
                    try FileManager.default.removeItem(atPath: path)
                    result["removed"] = true
                } catch let error as CocoaError where error.code == .fileNoSuchFile {
                    result["removed"] = true
                    result["note"] = "already absent"
                } catch {
                    result["removed"] = false
                    result["error"] = error.localizedDescription
                }
            case .expire:
                write(beatAt: 0)
                result["wrote_beat_at"] = 0
                if let lastError { result["error"] = lastError }
            }
            result["exists_after"] = FileManager.default.fileExists(atPath: path)
            return result
        }
    }

    /// On `queue` only.
    private func write(beatAt: TimeInterval?) {
        let url = URL(fileURLWithPath: path)
        let temporary = path + ".shell.tmp"
        let stamp = beatAt ?? Date().timeIntervalSince1970
        do {
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            FileManager.default.createFile(atPath: temporary, contents: nil, attributes: [.posixPermissions: 0o600])
            try Data(LeaseContract.body(beatAt: stamp).utf8).write(to: URL(fileURLWithPath: temporary))
            guard rename(temporary, path) == 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
            if beatAt == nil { history.append(stamp) }
            lastError = nil
        } catch {
            lastError = error.localizedDescription
            shellLog("[shell][lease] beat failed: \(error.localizedDescription)")
        }
    }
}
