// --verify-lease: headless lifecycle-lease check against the dev/test stack only (isolated JAEGER_STATE_DIR).
// Start the dev stack (lease acquired), sample beats + gateway health past the 15 s grace, retire (remove),
// sample again past the grace. With --also-expire (dev build), re-acquire and retire the old way (beat_at 0)
// to show what the Gateway does then. Never touches the operator's ~/.jaeger lease (stat only).
import AppKit
import JaegerShellCore

final class LeaseVerifier {
    unowned let app: JaegerShellApplication
    private var report: [String: Any] = [:]
    private var finished = false
    private let alsoExpire = CommandLine.arguments.contains("--also-expire")
    private let t0 = Date()
    private let gatewayLog = "/tmp/jaeger-uirebuild-dev-gateway.log"

    init(app: JaegerShellApplication) { self.app = app }

    private var realPath: String { LeaseContract.realOperatorPath(home: NSHomeDirectory()) }
    private func realStat() -> [String: Any] {
        guard let a = try? FileManager.default.attributesOfItem(atPath: realPath) else { return ["exists": false] }
        return ["exists": true, "size": (a[.size] as? NSNumber)?.intValue ?? -1,
                "mtime": (a[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0]
    }
    private func ports() -> [String: Bool] {
        guard let dev = app.stack.dev else { return [:] }
        return [String(dev.gatewayPort): !StackController.isListening(dev.gatewayPort),
                String(dev.uiPort): !StackController.isListening(dev.uiPort)]
    }
    private func logLines() -> [String] {
        let text = (try? String(contentsOfFile: gatewayLog, encoding: .utf8)) ?? ""
        return text.split(separator: "\n").map(String.init)
            .filter { $0.localizedCaseInsensitiveContains("lifecycle") || $0.contains("launchd stack") }
            .suffix(8).map { String($0.prefix(220)) }
    }

    func run() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 170) { [weak self] in self?.finish("timeout") }
        report["real_lease_before"] = realStat()
        guard let dev = app.stack.dev else {
            return finish("dev_stack_unavailable: needs a dev build, JAEGER_SHELL_STACK_MODE=dev and JAEGER_SHELL_DEV_ROOT")
        }
        report["lease_path"] = app.stack.leasePath
        report["state_dir"] = dev.stateDir
        report["gateway"] = dev.gatewayOrigin.string
        report["contract"] = ["suspend_after_s": LeaseContract.suspendAfter, "shutdown_grace_s": LeaseContract.shutdownGrace,
                              "beat_interval_s": LeaseContract.beatInterval]
        report["ports_free_before"] = ports()
        app.stack.start { [weak self] result, error in
            guard let self else { return }
            self.report["start"] = result ?? ["error": error ?? "?"]
            guard error == nil else { return self.stopAndFinish(error: "dev stack start failed: \(error ?? "?")") }
            self.report["lease_held_after_start"] = self.app.stack.lease?.isRunning ?? false
            self.sample("held", count: 13) {
                self.report["retire_remove"] = self.app.stack.retireLease("verify: retire (remove)")
                self.sample("after_retire", count: 10) {
                    self.report["gateway_log_after_retire"] = self.logLines()
                    guard self.alsoExpire else { return self.stopAndFinish(error: nil) }
                    self.app.stack.acquireLease("verify: re-acquire for the old-app comparison")
                    DispatchQueue.main.asyncAfter(deadline: .now() + 4) {
                        self.report["retire_expire"] = self.app.stack.retireLease("verify: retire the old way (beat_at 0)", mode: .expire)
                        self.sample("after_expire", count: 12, stopWhenGatewayGone: true) {
                            // the expired lease is a test artifact in the isolated state dir; don't leave it behind
                            try? FileManager.default.removeItem(atPath: self.app.stack.leasePath)
                            self.report["expired_test_lease_removed"] = !FileManager.default.fileExists(atPath: self.app.stack.leasePath)
                            self.stopAndFinish(error: nil)
                        }
                    }
                }
            }
        }
    }

    private func sample(_ phase: String, count: Int, stopWhenGatewayGone: Bool = false, then: @escaping () -> Void) {
        var rows: [[String: Any]] = []
        func tick(_ i: Int) {
            let path = app.stack.leasePath
            let text = try? String(contentsOfFile: path, encoding: .utf8)
            let now = Date().timeIntervalSince1970
            let alive = app.stack.gatewayAlive
            ShellEnvironment.probe(app.stack.dev!.gatewayOrigin.string + "/health") { [weak self] health in
                guard let self else { return }
                rows.append([
                    "t": (Date().timeIntervalSince(self.t0) * 10).rounded() / 10,
                    "beat_at": text.flatMap { LeaseContract.beatAt(contents: $0) } ?? NSNull(),
                    "decision": LeaseContract.decide(contents: text, now: now).label,
                    "health": health, "gateway_alive": alive,
                ])
                self.report["samples_" + phase] = rows
                if i + 1 >= count || (stopWhenGatewayGone && !alive && i > 0) { return then() }
                DispatchQueue.main.asyncAfter(deadline: .now() + 2) { tick(i + 1) }
            }
        }
        tick(0)
    }

    private func stopAndFinish(error: String?) {
        report["gateway_log_end"] = logLines()
        app.stack.stop { [weak self] result, stopError in
            guard let self else { return }
            self.report["stop"] = result ?? ["error": stopError ?? "?"]
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                self.report["ports_free_after"] = self.ports()
                self.finish(error)
            }
        }
    }

    private func rows(_ phase: String) -> [[String: Any]] { report["samples_" + phase] as? [[String: Any]] ?? [] }
    private func span(_ r: [[String: Any]]) -> Double {
        guard let a = r.first?["t"] as? Double, let b = r.last?["t"] as? Double else { return 0 }
        return b - a
    }

    private func finish(_ error: String?) {
        guard !finished else { return }
        finished = true
        if let error { report["error"] = error }
        report["real_lease_after"] = realStat()
        let held = rows("held"), after = rows("after_retire")
        let beats = held.compactMap { $0["beat_at"] as? Double }
        let healthy: ([String: Any]) -> Bool = { $0["health"] as? String == "running" && $0["gateway_alive"] as? Bool == true }
        let grace = LeaseContract.shutdownGrace
        let path = report["lease_path"] as? String ?? ""
        var checks: [String: Bool] = [
            "lease_path_isolated": path.hasPrefix((report["state_dir"] as? String ?? "?") + "/") && path != realPath,
            "lease_acquired_on_start": report["lease_held_after_start"] as? Bool == true,
            "heartbeats_advancing": beats.count == held.count && beats.count >= 10 && zip(beats, beats.dropFirst()).allSatisfy { $1 > $0 },
            "decision_alive_while_held": !held.isEmpty && held.allSatisfy { $0["decision"] as? String == "alive" },
            "gateway_up_past_grace_while_held": !held.isEmpty && held.allSatisfy(healthy) && span(held) > grace,
            "retire_removed_lease": (report["retire_remove"] as? [String: Any])?["removed"] as? Bool == true
                && !after.isEmpty && after.allSatisfy { $0["decision"] as? String == "no_lease" },
            "gateway_up_after_retire_past_grace": !after.isEmpty && after.allSatisfy(healthy) && span(after) > grace,
            "no_shutdown_logged_after_remove": !((report["gateway_log_after_retire"] as? [String]) ?? []).contains { $0.contains("disappeared") },
            "real_lease_untouched": NSDictionary(dictionary: report["real_lease_before"] as? [String: Any] ?? [:])
                .isEqual(to: report["real_lease_after"] as? [String: Any] ?? ["x": 1]),
            "no_production_stack_call": app.stack.productionInvocations == 0,
            "ports_free_after": !(report["ports_free_after"] as? [String: Bool] ?? [:]).isEmpty
                && (report["ports_free_after"] as? [String: Bool] ?? [:]).values.allSatisfy { $0 },
        ]
        if alsoExpire {
            let expired = rows("after_expire")
            checks["expired_lease_stops_dev_gateway"] = expired.last?["gateway_alive"] as? Bool == false
        }
        report["checks"] = checks
        report["ok"] = error == nil && checks.values.allSatisfy { $0 }
        if let data = try? JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]) {
            FileHandle.standardOutput.write(data + Data("\n".utf8))
        }
        NSApp.terminate(nil)
    }
}
