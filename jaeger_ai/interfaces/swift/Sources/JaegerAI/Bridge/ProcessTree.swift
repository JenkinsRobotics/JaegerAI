import Darwin
import Foundation

/// Reap a spawned process and every descendant so Quit cannot leave orphans.
///
/// Foundation `Process.terminate()` only signals the direct child. The
/// Jaeger bridge then ARESNativeMCP (and any other grandchildren) sit under
/// that child; SIGKILL or Force Quit reparents them to launchd. Snapshot
/// the tree first, SIGTERM everyone, then SIGKILL whoever is still alive.
enum ProcessTree {
    static func isAlive(_ pid: pid_t) -> Bool {
        pid > 1 && kill(pid, 0) == 0
    }

    /// Direct + nested children of `root` according to a live `ps` snapshot.
    /// Does not include `root`. Empty when `root` is already dead (children
    /// will have been reparented to launchd) — callers that need to survive
    /// that race must snapshot before waiting.
    static func descendants(of root: pid_t) -> [pid_t] {
        guard root > 1 else { return [] }
        let byParent = parentMap()
        var found: [pid_t] = []
        var queue: [pid_t] = [root]
        var seen: Set<pid_t> = [root]
        while !queue.isEmpty {
            let parent = queue.removeFirst()
            for (pid, ppid) in byParent where ppid == parent && !seen.contains(pid) {
                seen.insert(pid)
                found.append(pid)
                queue.append(pid)
            }
        }
        return found
    }

    /// SIGTERM every pid in the tree (snapshot first), wait, SIGKILL leftovers.
    /// Rescans under `root` during the wait so late forks are included.
    static func terminate(root: pid_t, graceSeconds: TimeInterval = 4) async {
        guard root > 1 else { return }
        var pids = Set(descendants(of: root))
        pids.insert(root)
        await terminate(pids: pids, graceSeconds: graceSeconds, rescanRoot: root)
    }

    static func terminate(
        pids: Set<pid_t>,
        graceSeconds: TimeInterval,
        rescanRoot: pid_t? = nil
    ) async {
        var remaining = Set(pids.filter { $0 > 1 })
        guard !remaining.isEmpty else { return }
        for pid in remaining {
            _ = kill(pid, SIGTERM)
        }
        let deadline = Date().addingTimeInterval(max(graceSeconds, 0))
        while Date() < deadline {
            if let root = rescanRoot, root > 1 {
                remaining.formUnion(descendants(of: root))
            }
            remaining = remaining.filter { isAlive($0) }
            if remaining.isEmpty { return }
            try? await Task.sleep(nanoseconds: 100_000_000)
        }
        if let root = rescanRoot, root > 1 {
            remaining.formUnion(descendants(of: root))
        }
        for pid in remaining where isAlive(pid) {
            _ = kill(pid, SIGKILL)
        }
        try? await Task.sleep(nanoseconds: 100_000_000)
    }

    /// Child that watches `parent` and reaps `root`'s tree if the parent dies
    /// without a graceful stop (Force Quit, crash). The returned process is
    /// owned by the caller and must be terminated on orderly shutdown so it
    /// does not fire after a clean stop.
    static func startParentDeathWatchdog(parent: pid_t, root: pid_t) -> Process? {
        guard parent > 1, root > 1 else { return nil }
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/sh")
        proc.arguments = ["-c", parentDeathWatchdogScript(parent: parent, root: root)]
        proc.standardInput = FileHandle.nullDevice
        proc.standardOutput = FileHandle.nullDevice
        proc.standardError = FileHandle.nullDevice
        do {
            try proc.run()
            return proc
        } catch {
            return nil
        }
    }

    static func parentDeathWatchdogScript(parent: pid_t, root: pid_t) -> String {
        """
        parent=\(parent)
        root=\(root)
        collect() {
          printf '%s\\n' "$1"
          for k in $(pgrep -P "$1" 2>/dev/null); do
            collect "$k"
          done
        }
        while kill -0 "$parent" 2>/dev/null; do
          sleep 0.4
        done
        pids=$(collect "$root" | awk 'NF && $1 > 1')
        [ -n "$pids" ] || exit 0
        kill -TERM $pids 2>/dev/null
        sleep 2
        kill -KILL $pids 2>/dev/null
        exit 0
        """
    }

    private static func parentMap() -> [pid_t: pid_t] {
        let output = run("/bin/ps", ["-axo", "pid=,ppid="])
        var map: [pid_t: pid_t] = [:]
        for line in output.split(whereSeparator: \.isNewline) {
            let cols = line.split(whereSeparator: \.isWhitespace)
            guard cols.count >= 2,
                  let pid = pid_t(cols[0]),
                  let ppid = pid_t(cols[1])
            else { continue }
            map[pid] = ppid
        }
        return map
    }

    private static func run(_ launchPath: String, _ arguments: [String]) -> String {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: launchPath)
        proc.arguments = arguments
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = FileHandle.nullDevice
        do {
            try proc.run()
            proc.waitUntilExit()
        } catch {
            return ""
        }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        return String(data: data, encoding: .utf8) ?? ""
    }
}
