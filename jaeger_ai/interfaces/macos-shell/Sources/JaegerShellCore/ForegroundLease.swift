// Explicit foreground lifecycle ownership. Never starts services or clears Stop.
import Foundation
import Darwin

public final class ForegroundLease {
    public static let argument = "--own-production-lifecycle"
    private let path: String
    private let stopPath: String
    private var descriptor: Int32 = -1
    private var stopped = false

    public init(path: String, stopPath: String) {
        self.path = path
        self.stopPath = stopPath
    }

    private func checkStop() throws {
        if stopped { throw Failure.refused("global_stop_observed_restart_shell_after_owner_release") }
        if FileManager.default.fileExists(atPath: stopPath) {
            guard let data = FileManager.default.contents(atPath: stopPath),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let engaged = object["engaged"] as? Bool, !engaged else {
                stopped = true
                throw Failure.refused("global_stop_engaged_or_unreadable")
            }
        }
    }

    public enum Failure: Error { case refused(String) }

    public func acquire() throws {
        try checkStop()
        guard descriptor == -1 else { return }
        try FileManager.default.createDirectory(at: URL(fileURLWithPath: path).deletingLastPathComponent(), withIntermediateDirectories: true)
        let fd = open(path + ".owner-lock", O_CREAT | O_RDWR | O_CLOEXEC, 0o600)
        guard fd >= 0 else { throw Failure.refused("ownership_lock_unavailable") }
        guard flock(fd, LOCK_EX | LOCK_NB) == 0 else {
            close(fd)
            throw Failure.refused("live_shell_owner")
        }
        do {
            if FileManager.default.fileExists(atPath: path) {
                let data = try Data(contentsOf: URL(fileURLWithPath: path))
                guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                      object["owner"] as? String == LeaseContract.owner,
                      let beat = object["beat_at"] as? Double, beat.isFinite else {
                    throw Failure.refused("foreign_or_unreadable_lease")
                }
                if let pid = object["shell_pid"] as? Int32, pid > 0,
                   kill(pid, 0) == 0 || errno == EPERM {
                    throw Failure.refused("live_shell_process")
                }
                guard Date().timeIntervalSince1970 - beat > LeaseContract.shutdownGrace else {
                    throw Failure.refused("recent_owner_heartbeat")
                }
            }
            try checkStop()
            descriptor = fd
            try heartbeat()
        } catch {
            descriptor = -1
            flock(fd, LOCK_UN)
            close(fd)
            throw error
        }
    }

    public func heartbeat() throws {
        guard descriptor >= 0 else { throw Failure.refused("ownership_not_acquired") }
        try checkStop()
        let data = try JSONSerialization.data(withJSONObject: [
            "owner": LeaseContract.owner, "beat_at": Date().timeIntervalSince1970,
            "shell_pid": getpid()
        ], options: [.sortedKeys])
        let temporary = path + ".foreground-\(getpid()).tmp"
        defer { try? FileManager.default.removeItem(atPath: temporary) }
        guard FileManager.default.createFile(atPath: temporary, contents: data, attributes: [.posixPermissions: 0o600]) else {
            throw Failure.refused("heartbeat_write_failed")
        }
        guard rename(temporary, path) == 0 else { throw Failure.refused("heartbeat_replace_failed") }
    }

    // Keep the last real heartbeat: never erase the lease or forge an expired beat.
    public func relinquish() {
        if descriptor >= 0 { flock(descriptor, LOCK_UN); close(descriptor); descriptor = -1 }
    }
    deinit { relinquish() }
}
