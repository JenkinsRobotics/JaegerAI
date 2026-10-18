// StackController.swift — Start / Stop / status of the Jaeger stack from the shell (Jaeger original;
// production path reuses the ported StackRunner + StackCLI from interfaces/swift StackManager.swift).
//
// production: `<launcher> stack up --json` / `stack down --json` (launchd-backed), only after a confirm
//             sheet, never in --verify-* modes, never in tests.
// dev:        DevStackConfig — the worktree gateway and the built main screen as this app's OWN foreground
//             child processes on 127.0.0.1 (isolated state). Refuses busy ports (never touches a process it
//             did not start) and stops its children by their own PIDs (SIGTERM, then SIGKILL after 8 s).

import AppKit
import Darwin
import JaegerShellCore

final class StackController {
    enum Action: String { case start, stop }

    unowned let app: JaegerShellApplication
    let mode: StackMode
    let dev: DevStackConfig?
    let devError: DevStackError?
    private var gatewayProc: Process?
    private var uiProc: Process?
    private var busy = false
    private(set) var productionInvocations = 0

    init(app: JaegerShellApplication) {
        self.app = app
        mode = StackMode.resolve(env: ProcessInfo.processInfo.environment, isDevBuild: ShellEnvironment.isDevBuild)
        switch ShellEnvironment.devStack {
        case .success(let config): dev = config; devError = nil
        case .failure(let error): dev = nil; devError = mode == .dev ? error : nil
        }
    }

    var summary: String {
        if let dev { return "dev: worktree gateway 127.0.0.1:\(dev.gatewayPort) + main screen 127.0.0.1:\(dev.uiPort)" }
        if mode == .dev { return "dev (unavailable: \(devError?.message ?? "?"))" }
        return "production: jaeger stack (launchd)"
    }

    static func isListening(_ port: Int) -> Bool {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        guard fd >= 0 else { return false }
        defer { close(fd) }
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = in_port_t(UInt16(port).bigEndian)
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        let result = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
        }
        return result == 0
    }

    // MARK: confirmation (menu always; bridge only for production)

    func confirmThen(_ action: Action, _ body: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = action == .start ? "Start the Jaeger stack?" : "Stop the Jaeger stack?"
        if let dev {
            alert.informativeText = action == .start
                ? "Dev mode: starts the worktree gateway (127.0.0.1:\(dev.gatewayPort)) and the main screen (127.0.0.1:\(dev.uiPort)) as this app's own processes, with isolated state. launchd is not used."
                : "Dev mode: stops the gateway and main screen this app started (by their own PIDs)."
        } else if let launcher = ShellEnvironment.launcherPath() {
            let args = action == .start ? StackCLI.upArguments : StackCLI.downArguments
            alert.informativeText = "This runs:\n\(launcher) \(args.joined(separator: " "))\n\n"
                + (action == .start ? "It starts the Jaeger services the same way the CLI does."
                                    : "It stops the Jaeger services the same way the CLI does.")
        } else {
            alert.informativeText = "No jaeger launcher was found (set JaegerLauncher in Info.plist or install the CLI)."
            alert.addButton(withTitle: "OK")
            alert.runModal()
            return
        }
        alert.addButton(withTitle: action == .start ? "Start" : "Stop")
        alert.addButton(withTitle: "Cancel")
        let handle: (NSApplication.ModalResponse) -> Void = { response in
            guard response == .alertFirstButtonReturn else { shellLog("[shell][stack] \(action.rawValue) cancelled"); return }
            body()
        }
        app.showWindow()
        if let window = app.mainWindow { alert.beginSheetModal(for: window, completionHandler: handle) } else { handle(alert.runModal()) }
    }

    /// Bridge entry: dev runs directly; production needs the confirm sheet and is refused in verify modes.
    func fromBridge(_ action: Action, done: @escaping BridgeDone) {
        if dev != nil { return action == .start ? start(done: done) : stop(done: done) }
        if mode == .dev { return done(nil, "dev_stack_unavailable: \(devError?.message ?? "?")") }
        if app.verifyMode || app.verifyBridgeMode { return done(nil, "production_stack_disabled_in_verify") }
        confirmThen(action) { [weak self] in
            guard let self else { return }
            action == .start ? self.start(done: done) : self.stop(done: done)
        }
        // no reply until the user decides; a cancel replies below via the sheet's cancel path
    }

    // MARK: start / stop

    func start(done: @escaping BridgeDone) {
        if let dev { return startDev(dev, done: done) }
        if mode == .dev { return done(nil, "dev_stack_unavailable: \(devError?.message ?? "?")") }
        runProduction(StackCLI.upArguments) { [weak self] result, error in
            if error == nil { self?.acquireLease("stack up") }
            done(result, error)
        }
    }

    func stop(done: @escaping BridgeDone) {
        if dev != nil { retireLease("dev stack stop"); return stopDev(done: done) }
        if mode == .dev { return done(nil, "dev_stack_unavailable: \(devError?.message ?? "?")") }
        retireLease("stack down")
        runProduction(StackCLI.downArguments, done: done)
    }

    // MARK: lifecycle lease (lifecycle_lease.py contract; LeaseBeat is the ported LifecycleLeaseBeat)

    private(set) var lease: LeaseBeat?
    var gatewayAlive: Bool { gatewayProc?.isRunning == true }
    private var headless: Bool { app.verifyMode || app.verifyBridgeMode || app.verifyLeaseMode || app.snapshotMode }

    /// Dev stack: its isolated JAEGER_STATE_DIR. Production: the same state-dir logic as lifecycle_lease.py.
    var leasePath: String {
        if let dev { return LeaseContract.path(stateDir: dev.stateDir) }
        return LeaseContract.path(env: ProcessInfo.processInfo.environment, home: NSHomeDirectory())
    }

    @discardableResult
    func acquireLease(_ reason: String) -> String? {
        let path = leasePath
        if headless && path == LeaseContract.realOperatorPath(home: NSHomeDirectory()) {
            shellLog("[shell][lease] refused: a headless check never touches the operator lease")
            return "refused_operator_lease_in_headless_check"
        }
        if mode == .dev && dev == nil { return "dev_stack_unavailable" }
        if lease?.isRunning == true { return nil }
        let beat = LeaseBeat(path: path)
        beat.start()
        lease = beat
        shellLog("[shell][lease] acquired (\(reason)) every \(Int(LeaseContract.beatInterval))s at \(path)")
        return nil
    }

    /// Default retire removes the lease (no shutdown); `.expire` only in dev builds.
    @discardableResult
    func retireLease(_ reason: String, mode requested: LeaseRetire? = nil) -> [String: Any] {
        guard let lease else { return ["retired": false, "reason": "no lease held"] }
        let configured = requested ?? LeaseRetire.resolve(env: ProcessInfo.processInfo.environment, isDevBuild: ShellEnvironment.isDevBuild)
        var result = lease.retire(LeaseRetire.allowed(configured, isDevBuild: ShellEnvironment.isDevBuild))
        self.lease = nil
        result["retired"] = true
        shellLog("[shell][lease] retired (\(reason)): \(result)")
        return result
    }

    /// Launch: hold the lease when the production stack is already running (never in headless checks).
    func acquireLeaseIfStackRunning() {
        guard !headless, dev == nil, mode == .production else { return }
        ShellEnvironment.probe(ShellEnvironment.gateway().origin.string + "/health") { [weak self] state in
            guard state == "running" else { return shellLog("[shell][lease] stack not running at launch (\(state)); no lease") }
            self?.acquireLease("stack running at launch")
        }
    }

    private func runProduction(_ arguments: [String], done: @escaping BridgeDone) {
        guard !headless else { return done(nil, "production_stack_disabled_in_verify") }
        guard let launcher = ShellEnvironment.launcherPath() else { return done(nil, "no_launcher") }
        guard !busy else { return done(nil, "busy") }
        busy = true
        productionInvocations += 1
        shellLog("[shell][stack] production \(launcher) \(arguments.joined(separator: " "))")
        StackRunner.run(launcher: launcher, arguments: arguments) { [weak self] data, stderr, status in
            self?.busy = false
            let reply = try? StackCLI.decodeAction(data)
            let summary = reply.map(StackCLI.summary) ?? "undecodable reply"
            shellLog("[shell][stack] \(arguments.dropFirst().first ?? "?") exited \(status): \(summary)\(stderr.isEmpty ? "" : " stderr=\(stderr.suffix(300))")")
            if let reply, reply.ok { done(["mode": "production", "summary": summary], nil) }
            else { done(nil, "stack_failed: \(summary)") }
        }
    }

    private func launch(_ command: ChildCommand, log path: String) throws -> Process {
        FileManager.default.createFile(atPath: path, contents: nil)
        let handle = FileHandle(forWritingAtPath: path)
        let process = Process()
        process.executableURL = URL(fileURLWithPath: command.executable)
        process.arguments = command.arguments
        process.environment = command.environment
        process.currentDirectoryURL = URL(fileURLWithPath: command.workingDirectory)
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = handle
        process.standardError = handle
        try process.run()
        shellLog("[shell][stack] dev child pid \(process.processIdentifier): \(URL(fileURLWithPath: command.executable).lastPathComponent) \(command.arguments.suffix(4).joined(separator: " "))")
        return process
    }

    private func waitHTTP(_ url: String, _ process: Process, deadline: Date, _ done: @escaping (Bool) -> Void) {
        ShellEnvironment.probe(url) { [weak self] text in
            if text == "running" { return done(true) }
            guard process.isRunning, Date() < deadline else { return done(false) }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self?.waitHTTP(url, process, deadline: deadline, done) }
        }
    }

    private func startDev(_ dev: DevStackConfig, done: @escaping BridgeDone) {
        if gatewayProc?.isRunning == true, uiProc?.isRunning == true { return status { done($0, nil) } }
        guard !busy else { return done(nil, "busy") }
        for port in [dev.gatewayPort, dev.uiPort] where Self.isListening(port) {
            return done(nil, "port_busy: 127.0.0.1:\(port) is already in use (not started by this app; left alone)")
        }
        guard FileManager.default.fileExists(atPath: dev.uiDist + "/index.html") else {
            return done(nil, "main_screen_not_built: run Scripts/build-main-screen.sh")
        }
        busy = true
        // A lease left in the isolated dev state dir (e.g. an expired one) would make the new dev gateway shut
        // down before the first beat. Dev state dir only; never the operator lease.
        let staleLease = LeaseContract.path(stateDir: dev.stateDir)
        if staleLease != LeaseContract.realOperatorPath(home: NSHomeDirectory()),
           FileManager.default.fileExists(atPath: staleLease) {
            try? FileManager.default.removeItem(atPath: staleLease)
            shellLog("[shell][lease] removed a leftover dev lease at \(staleLease)")
        }
        let home = NSHomeDirectory()
        let gateway: Process
        do { gateway = try launch(dev.gatewayCommand(home: home), log: "/tmp/jaeger-uirebuild-dev-gateway.log") } catch {
            busy = false
            return done(nil, "gateway_launch_failed: \(error.localizedDescription)")
        }
        gatewayProc = gateway
        waitHTTP(dev.gatewayOrigin.string + "/health", gateway, deadline: Date() + 45) { [weak self] healthy in
            guard let self else { return }
            guard healthy else {
                self.terminateOwn { self.busy = false; done(nil, "gateway_not_healthy (see /tmp/jaeger-uirebuild-dev-gateway.log)") }
                return
            }
            let ui: Process
            do { ui = try self.launch(dev.uiCommand(home: home), log: "/tmp/jaeger-uirebuild-dev-ui.log") } catch {
                self.terminateOwn { self.busy = false; done(nil, "main_screen_launch_failed: \(error.localizedDescription)") }
                return
            }
            self.uiProc = ui
            self.waitHTTP(dev.uiOrigin.string + "/", ui, deadline: Date() + 30) { ready in
                guard ready else {
                    self.terminateOwn { self.busy = false; done(nil, "main_screen_not_ready (see /tmp/jaeger-uirebuild-dev-ui.log)") }
                    return
                }
                self.busy = false
                shellLog("[shell][stack] dev stack running (gateway pid \(gateway.processIdentifier), main screen pid \(ui.processIdentifier))")
                self.acquireLease("dev stack started")
                self.status { done($0, nil) }
            }
        }
    }

    /// SIGTERM own children, SIGKILL after 8 s; never signals any other PID.
    private func terminateOwn(_ then: @escaping () -> Void) {
        let procs = [uiProc, gatewayProc].compactMap { $0 }
        for p in procs where p.isRunning { p.terminate() }
        DispatchQueue.global().async {
            let end = Date() + 8
            while procs.contains(where: \.isRunning) && Date() < end { usleep(100_000) }
            for p in procs where p.isRunning { kill(p.processIdentifier, SIGKILL) }
            while procs.contains(where: \.isRunning) { usleep(50_000) }
            DispatchQueue.main.async { then() }
        }
    }

    private func stopDev(done: @escaping BridgeDone) {
        guard let dev else { return done(nil, "dev_stack_unavailable") }
        let pids = [gatewayProc, uiProc].compactMap { $0?.processIdentifier }
        guard !pids.isEmpty else { return done(["stopped": false, "reason": "not started by this app"], nil) }
        terminateOwn { [weak self] in
            self?.gatewayProc = nil
            self?.uiProc = nil
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                let free = [String(dev.gatewayPort): !Self.isListening(dev.gatewayPort), String(dev.uiPort): !Self.isListening(dev.uiPort)]
                shellLog("[shell][stack] dev stack stopped pids \(pids) ports_free \(free)")
                done(["stopped": true, "pids": pids, "ports_free": free], nil)
            }
        }
    }

    /// App quit: stop own dev children (never production).
    func shutdown() {
        let procs = [uiProc, gatewayProc].compactMap { $0 }
        for p in procs where p.isRunning { p.terminate() }
        let end = Date() + 5
        while procs.contains(where: \.isRunning) && Date() < end { usleep(100_000) }
        for p in procs where p.isRunning { kill(p.processIdentifier, SIGKILL) }
    }

    // MARK: status

    func status(_ done: @escaping ([String: Any]) -> Void) {
        guard let dev else {
            ShellEnvironment.stackStatus(app.start) { result in
                var r = result
                r["mode"] = self.mode == .dev ? "dev_unavailable" : "production"
                if let e = self.devError { r["dev_error"] = e.message }
                done(r)
            }
            return
        }
        var gateway: [String: Any] = ["port": dev.gatewayPort, "pid": gatewayProc.map { Int($0.processIdentifier) } ?? NSNull(),
                                      "own_child_running": gatewayProc?.isRunning ?? false]
        var ui: [String: Any] = ["port": dev.uiPort, "pid": uiProc.map { Int($0.processIdentifier) } ?? NSNull(),
                                 "own_child_running": uiProc?.isRunning ?? false]
        let group = DispatchGroup()
        group.enter(); ShellEnvironment.probe(dev.gatewayOrigin.string + "/health") { gateway["health"] = $0; group.leave() }
        group.enter(); ShellEnvironment.probe(dev.uiOrigin.string + "/") { ui["http"] = $0; group.leave() }
        group.notify(queue: .main) {
            let running = (gateway["own_child_running"] as? Bool == true) && (ui["own_child_running"] as? Bool == true)
                && gateway["health"] as? String == "running" && ui["http"] as? String == "running"
            done(["mode": "dev", "running": running, "gateway": gateway, "main_screen": ui, "state_dir": dev.stateDir])
        }
    }
}
