//
//  BridgeProcess.swift
//  JaegerOS / Bridge
//
//  Out-of-process transport to the agent: spawns ``jaeger bridge`` (the
//  Python NDJSON stdio bridge) as a child and exchanges newline-JSON over
//  its stdin/stdout.  Protocol v1 — the single wire contract lives in
//  ``jaeger_os/interfaces/protocol.py`` with cross-language fixtures in
//  ``protocol_v1_fixtures.json`` (decoded by ProtocolFixtureTests here).
//
//  Phase-1 hardening (SWIFT_APP_ARCHITECTURE_PLAN.md):
//   * FAST READY — ``ready`` arrives before the model boots (transport
//     usable immediately); ``agent_state`` frames stream booting→ready.
//   * NO HANGS — every await has a timeout; termination resumes every
//     pending continuation with a typed failure and clears pipe handlers.
//   * CLEAN-EXIT — the Python side emits ``bye`` before exiting (its exit
//     code is unreliable — ggml Metal teardown), so "bye seen" is the
//     orderly-shutdown signal and anything else is a crash.
//

import Foundation

/// Ready handshake — the TRANSPORT is up. ``agent`` says whether the model
/// is already warm ("ready") or still coming up ("booting" → watch
/// ``onAgentState``).
struct BridgeReady: Sendable {
    let instance: String
    let model: String?
    let character: String?   // active character's display name (the persona)
    let icon: String?        // absolute path to the effective avatar
    let proto: String        // protocol version the bridge speaks
    let capabilities: [String]
    let agent: String        // "ready" | "booting"
    let agentName: String?   // the AGENT's name (identity.yaml) — lead with this
}

/// Agent lifecycle, decoupled from transport readiness.
enum AgentLifecycle: Sendable, Equatable {
    case booting
    case ready(model: String?, character: String?, icon: String?,
               agentName: String?)
    case failed(String)
}

/// A permission/clarify request the agent raised mid-turn. Answer with
/// ``BridgeProcess.respond(id:answer:)``.
struct BridgeRequest: Sendable {
    let id: String
    let kind: String        // approval | clarify | secret
    let prompt: String
    let options: [String]
}

enum BridgeError: Error, LocalizedError {
    case launchFailed(String)
    case bootFailed(String)
    case locked(String)         // another process holds the instance lock
    case notRunning
    case timeout(String)
    case terminated(String)     // child died (no ``bye`` = crash)

    var errorDescription: String? {
        switch self {
        case .launchFailed(let m): return "couldn't launch jaeger bridge: \(m)"
        case .bootFailed(let m): return m
        case .locked(let m): return "instance already running: \(m)"
        case .notRunning: return "agent bridge not running"
        case .timeout(let m): return "bridge timed out: \(m)"
        case .terminated(let m): return "bridge exited: \(m)"
        }
    }
}

/// Reply to a query/command. ``json`` is the serialized ``data`` payload —
/// decode it into a typed struct with ``JSONDecoder``.
struct QueryResult: Sendable {
    let ok: Bool
    let error: String?
    let json: Data?
}

/// One finished chat turn. The telemetry trio is v1 ADDITIVE — nil when
/// the core didn't send it (older core, error paths, slash replies).
struct TurnResult: Sendable {
    let text: String
    let error: String?
    var elapsedS: Double? = nil   // wall-clock turn time ("replied in 3s")
    var ctxUsed: Int? = nil       // estimated prompt tokens in the session
    var ctxMax: Int? = nil        // the loaded model's context window
}

/// Owns the child process + NDJSON framing. One pending turn at a time
/// (the UI disables send while a turn is in flight).
actor BridgeProcess {

    // Timeouts. ``ready`` is fast now (no model boot ahead of it) so a
    // short fuse catches a wedged child instead of hanging the splash.
    static let readyTimeout: Duration = .seconds(20)
    static let requestTimeout: Duration = .seconds(15)
    static let turnTimeout: Duration = .seconds(600)   // model turns are slow

    private var process: Process?
    private var stdin: FileHandle?
    private var stdout: FileHandle?
    private let framer = FrameStream()
    private var sawBye = false

    private var readyCont: CheckedContinuation<BridgeReady, Error>?
    private var replyCont: CheckedContinuation<TurnResult, Never>?

    // Correlated query/command requests (id → waiter).
    private var reqCounter = 0
    private var resultConts: [String: CheckedContinuation<QueryResult, Never>] = [:]

    // MARK: - Callbacks (set by AgentBridge)

    var onState: (@Sendable (Bool) -> Void)?
    var onTool: (@Sendable (String, String, Double, String?) -> Void)?
    var onAgentState: (@Sendable (AgentLifecycle) -> Void)?
    var onRequest: (@Sendable (BridgeRequest) -> Void)?
    /// Fired for every ``fatal`` frame with its ``kind`` — the transport
    /// may STAY alive after one (kind ``no_instance``: first-run, the
    /// bridge keeps serving queries so onboarding can run over it).
    /// ``suggestedName`` (v1 additive) rides ``no_instance`` — the
    /// operator's CLI-pinned agent name, or nil.
    var onFatal: (@Sendable (_ kind: String, _ error: String,
                             _ suggestedName: String?) -> Void)?
    /// Fired once when the child exits. ``clean`` = a ``bye`` frame was
    /// seen (orderly); false = crash/kill.
    var onTermination: (@Sendable (_ clean: Bool) -> Void)?

    func setOnState(_ cb: @escaping @Sendable (Bool) -> Void) { onState = cb }
    func setOnTool(_ cb: @escaping @Sendable (String, String, Double, String?) -> Void) { onTool = cb }
    func setOnAgentState(_ cb: @escaping @Sendable (AgentLifecycle) -> Void) { onAgentState = cb }
    func setOnRequest(_ cb: @escaping @Sendable (BridgeRequest) -> Void) { onRequest = cb }
    func setOnFatal(_ cb: @escaping @Sendable (String, String, String?) -> Void) { onFatal = cb }
    func setOnTermination(_ cb: @escaping @Sendable (Bool) -> Void) { onTermination = cb }

    // MARK: - Queries / commands

    /// Ask the bridge for read-only data (characters, config, permissions).
    func query(_ what: String, args: [String: any Sendable] = [:]) async -> QueryResult {
        await request(["op": "query", "what": what, "args": args])
    }

    /// Run a mutation (select/make-default/save…). ``ok``/``error`` on the result.
    func command(_ cmd: String, args: [String: any Sendable] = [:]) async -> QueryResult {
        await request(["op": "command", "cmd": cmd, "args": args])
    }

    private func request(_ base: [String: any Sendable]) async -> QueryResult {
        reqCounter += 1
        let id = "r\(reqCounter)"
        var obj = base
        obj["id"] = id
        guard let stdin,
              let data = try? JSONSerialization.data(withJSONObject: obj) else {
            return QueryResult(ok: false, error: "bridge not running", json: nil)
        }
        let timeout = Task {
            try? await Task.sleep(for: Self.requestTimeout)
            await self.expireRequest(id)
        }
        defer { timeout.cancel() }
        return await withCheckedContinuation { cont in
            resultConts[id] = cont
            var line = data
            line.append(0x0A)
            try? stdin.write(contentsOf: line)
        }
    }

    private func expireRequest(_ id: String) {
        resultConts.removeValue(forKey: id)?
            .resume(returning: QueryResult(ok: false,
                                           error: "bridge timed out", json: nil))
    }

    /// Answer a pending ``request`` frame (permission approval etc.).
    func respond(id: String, answer: String) {
        write(["op": "respond", "id": id, "answer": answer])
    }

    // MARK: - Lifecycle

    /// Resolve the ``jaeger`` launcher. ``$JAEGER_BRIDGE_CMD`` overrides
    /// outright; then a dev bundle self-locates the repo it was built in
    /// (JaegerOS-dev.app lives at ``<repo>/…/swift/.build/``, so walking
    /// up from the bundle finds ``<repo>/jaeger`` — no PATH games); then
    /// ``$JAEGER_REPO/jaeger``; else the dev-tree default.
    static func jaegerPath() -> String {
        let env = ProcessInfo.processInfo.environment
        if let cmd = env["JAEGER_BRIDGE_CMD"], !cmd.isEmpty { return cmd }
        var dir = URL(fileURLWithPath: Bundle.main.bundlePath)
            .deletingLastPathComponent()
        for _ in 0..<8 {
            let candidate = dir.appendingPathComponent("jaeger").path
            if FileManager.default.isExecutableFile(atPath: candidate) {
                return candidate
            }
            if dir.path == "/" { break }
            dir.deleteLastPathComponent()
        }
        let repo = (env["JAEGER_REPO"].flatMap { $0.isEmpty ? nil : $0 })
            ?? (NSHomeDirectory() as NSString).appendingPathComponent("GITHUB/JROS")
        return (repo as NSString).appendingPathComponent("jaeger")
    }

    /// Launch the bridge and await its ``ready`` frame (or ``fatal``).
    /// FAST: ready means the transport is up, not that the model is loaded
    /// — watch ``onAgentState`` for booting → ready. ``instance`` pins the
    /// bridge to a named instance (the dev app passes ``jros-dev`` via
    /// LSEnvironment); nil lets the bridge resolve its own default.
    func start(instance: String? = nil) async throws -> BridgeReady {
        guard process == nil else { throw BridgeError.launchFailed("already running") }

        let path = Self.jaegerPath()
        guard FileManager.default.isExecutableFile(atPath: path) else {
            throw BridgeError.launchFailed("\(path) not executable (set $JAEGER_REPO)")
        }

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: path)
        proc.arguments = instance.map { ["bridge", $0] } ?? ["bridge"]
        proc.currentDirectoryURL =
            URL(fileURLWithPath: (path as NSString).deletingLastPathComponent)

        let inPipe = Pipe()
        let outPipe = Pipe()
        proc.standardInput = inPipe
        proc.standardOutput = outPipe
        proc.standardError = FileHandle.standardError   // boot logs → Console

        outPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard let self, !data.isEmpty else { return }
            Task { await self.ingest(data) }
        }
        proc.terminationHandler = { [weak self] _ in
            Task { await self?.handleTermination() }
        }

        do {
            try proc.run()
        } catch {
            outPipe.fileHandleForReading.readabilityHandler = nil
            throw BridgeError.launchFailed(error.localizedDescription)
        }
        self.process = proc
        self.stdin = inPipe.fileHandleForWriting
        self.stdout = outPipe.fileHandleForReading

        let timeout = Task {
            try? await Task.sleep(for: Self.readyTimeout)
            await self.expireReady()
        }
        defer { timeout.cancel() }
        return try await withCheckedThrowingContinuation { cont in
            self.readyCont = cont
        }
    }

    private func expireReady() {
        readyCont?.resume(throwing: BridgeError.timeout("no ready frame"))
        readyCont = nil
    }

    /// Send one turn and await the agent's reply. ``session`` keeps each
    /// window/conversation isolated on the Python side (sessions.db).
    func runTurn(_ text: String, session: String = "desktop-app")
        async -> TurnResult
    {
        guard process != nil else {
            return TurnResult(text: "", error: "agent bridge not running")
        }
        write(["op": "send", "text": text, "session": session])
        let timeout = Task {
            try? await Task.sleep(for: Self.turnTimeout)
            await self.expireTurn()
        }
        defer { timeout.cancel() }
        return await withCheckedContinuation { cont in
            self.replyCont = cont
        }
    }

    private func expireTurn() {
        replyCont?.resume(returning: TurnResult(text: "", error: "turn timed out"))
        replyCont = nil
    }

    /// Immediate stop: quit op + SIGTERM. Use ``quitGracefully()`` for the
    /// tray-quit path so the core frees the model and exits with ``bye``.
    func stop() {
        write(["op": "quit"])
        stdout?.readabilityHandler = nil
        process?.terminate()
        drainAll(reason: "bridge stopped")
        process = nil
        stdin = nil
        stdout = nil
    }

    /// Orderly shutdown for Quit-from-tray: send ``quit``, give the core up
    /// to ``grace`` to tear down (model free + bye + clean exit), then
    /// SIGTERM as the fallback. The windows-close-freely / quit-from-tray
    /// lifetime means this is the ONE place the core's life ends.
    func quitGracefully(grace: Duration = .seconds(10)) async {
        guard let proc = process else { return }
        write(["op": "quit"])
        let deadline = ContinuousClock.now + grace
        while proc.isRunning && ContinuousClock.now < deadline {
            try? await Task.sleep(for: .milliseconds(200))
        }
        if proc.isRunning { proc.terminate() }
        stdout?.readabilityHandler = nil
        drainAll(reason: "bridge stopped")
        process = nil
        stdin = nil
        stdout = nil
    }

    // MARK: - internals

    /// Resume EVERY pending continuation — nothing may hang past the
    /// child's death (the review's headline finding).
    private func drainAll(reason: String) {
        readyCont?.resume(throwing: BridgeError.terminated(reason))
        readyCont = nil
        replyCont?.resume(returning: TurnResult(text: "", error: reason))
        replyCont = nil
        for (_, cont) in resultConts {
            cont.resume(returning: QueryResult(ok: false, error: reason, json: nil))
        }
        resultConts.removeAll()
    }

    private func ingest(_ data: Data) {
        for frame in framer.feed(data) {
            guard let f = ProtocolFrame.decode(frame) else { continue }
            switch f {
            case .ready(let r):
                readyCont?.resume(returning: r)
                readyCont = nil
            case .agentState(let s):
                onAgentState?(s)
            case .result(let id, let ok, let error, let data):
                resultConts.removeValue(forKey: id)?
                    .resume(returning: QueryResult(ok: ok, error: error, json: data))
            case .state(let busy):
                onState?(busy)
            case .tool(let name, let phase, let elapsed, let detail):
                onTool?(name, phase, elapsed, detail)
            case .reply(let text, let error, let elapsed, let used, let mx):
                replyCont?.resume(returning: TurnResult(
                    text: text, error: error,
                    elapsedS: elapsed, ctxUsed: used, ctxMax: mx))
                replyCont = nil
            case .request(let r):
                onRequest?(r)
            case .fatal(let error, let kind, let suggestedName):
                let err: BridgeError = kind == "locked"
                    ? .locked(error) : .bootFailed(error)
                readyCont?.resume(throwing: err)
                readyCont = nil
                onFatal?(kind, error, suggestedName)
                onAgentState?(.failed(error))
                replyCont?.resume(returning: TurnResult(text: "", error: error))
                replyCont = nil
            case .bye:
                sawBye = true
            }
        }
    }

    private func handleTermination() {
        stdout?.readabilityHandler = nil
        let clean = sawBye
        drainAll(reason: clean ? "bridge shut down" : "bridge crashed")
        process = nil
        stdin = nil
        stdout = nil
        onTermination?(clean)
    }

    private func write(_ obj: [String: Any]) {
        guard let stdin,
              var data = try? JSONSerialization.data(withJSONObject: obj)
        else { return }
        data.append(0x0A)
        try? stdin.write(contentsOf: data)
    }
}
