// --verify-lease-policy: headless (no window, menu, status item or hotkey). Runs the real launch-time lease path
// (acquireLeaseIfStackRunning) against JAEGER_SHELL_GATEWAY_URL with JAEGER_LIFECYCLE_LEASE pointed at a temp file,
// then reports whether that file was created or modified. Refuses any lease path outside the temp dirs or under
// ~/.jaeger, so it can never touch the operator's lease.
import AppKit
import JaegerShellCore

enum LeasePolicyCheck {
    static func stat(_ path: String) -> [String: Any] {
        guard let a = try? FileManager.default.attributesOfItem(atPath: path) else { return ["exists": false] }
        return ["exists": true, "mtime": ((a[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0), "size": (a[.size] as? Int) ?? 0]
    }

    static func finish(_ report: [String: Any], code: Int32) -> Never {
        let data = (try? JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])) ?? Data()
        FileHandle.standardOutput.write(data + Data("\n".utf8))
        exit(code)
    }

    static func run(app: JaegerShellApplication) {
        let raw = ProcessInfo.processInfo.environment[LeaseContract.envKey] ?? ""
        let path = (raw as NSString).standardizingPath
        let tmpRoots = ["/tmp/", "/private/tmp/", (NSTemporaryDirectory() as NSString).standardizingPath + "/"]
        guard !path.isEmpty, tmpRoots.contains(where: { path.hasPrefix($0) }), !path.contains("/.jaeger/"),
              path != LeaseContract.realOperatorPath(home: NSHomeDirectory()) else {
            finish(["ok": false, "error": "refused: JAEGER_LIFECYCLE_LEASE must be a temp file (never the operator lease)"], code: 2)
        }
        var report: [String: Any] = ["policy": app.stack.leasePolicy.isEnabled ? "enabled" : "disabled",
                                     "reason": app.stack.leasePolicy.reason, "temp_lease": path,
                                     "gateway": ShellEnvironment.gateway().origin.string, "before": stat(path)]
        app.stack.acquireLeaseIfStackRunning(allowHeadless: true)
        DispatchQueue.main.asyncAfter(deadline: .now() + 6) {
            let before = report["before"] as? [String: Any] ?? [:], after = stat(path)
            report["after"] = after
            report["created"] = (before["exists"] as? Bool) != true && (after["exists"] as? Bool) == true
            report["modified"] = (before["mtime"] as? Double) != (after["mtime"] as? Double)
            report["held"] = app.stack.lease?.isRunning ?? false
            report["retire"] = app.stack.retireLease("verify-lease-policy done")
            report["ok"] = true
            finish(report, code: 0)
        }
    }
}
