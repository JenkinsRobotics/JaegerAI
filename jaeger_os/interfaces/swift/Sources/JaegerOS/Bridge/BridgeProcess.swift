//
//  BridgeProcess.swift
//  JaegerOS / Bridge
//
//  Out-of-process transport to the agent: spawns ``jaeger bridge`` (the
//  Python NDJSON stdio bridge) as a child and exchanges newline-JSON over
//  its stdin/stdout.  The SAME agent the PySide6 app runs in-process,
//  one hop out — no socket, no port, no agent.  Each app instance owns
//  its own child (1:1); there's no shared server to manage.
//
//  Protocol (one JSON object per line) — mirror of
//  ``jaeger_os/interfaces/bridge.py``:
//
//    bridge → us (stdout):
//      {"type":"ready","instance":<str>,"model":<str?>}
//      {"type":"state","busy":<bool>}
//      {"type":"reply","text":<str>,"error":<str?>}
//      {"type":"fatal","error":<str>}
//    us → bridge (stdin):
//      {"text":<str>}      one turn
//      {"op":"quit"}       graceful stop
//

import Foundation

/// Ready handshake — what the bridge reports once the model is loaded.
struct BridgeReady: Sendable {
    let instance: String
    let model: String?
    let character: String?   // active character's display name
    let icon: String?        // absolute path to its profile image
}

enum BridgeError: Error, LocalizedError {
    case launchFailed(String)
    case bootFailed(String)
    case notRunning

    var errorDescription: String? {
        switch self {
        case .launchFailed(let m): return "couldn't launch jaeger bridge: \(m)"
        case .bootFailed(let m): return m
        case .notRunning: return "agent bridge not running"
        }
    }
}

/// Owns the child process + NDJSON framing. One pending turn at a time
/// (the UI disables send while a turn is in flight), so a single reply
/// continuation is sufficient.
/// Reply to a query/command. ``json`` is the serialized ``data`` payload —
/// decode it into a typed struct with ``JSONDecoder``.
struct QueryResult: Sendable {
    let ok: Bool
    let error: String?
    let json: Data?
}

actor BridgeProcess {

    private var process: Process?
    private var stdin: FileHandle?
    private let framer = FrameStream()

    private var readyCont: CheckedContinuation<BridgeReady, Error>?
    private var replyCont: CheckedContinuation<(text: String, error: String?), Never>?

    // Correlated query/command requests (id → waiter).
    private var reqCounter = 0
    private var resultConts: [String: CheckedContinuation<QueryResult, Never>] = [:]

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
        return await withCheckedContinuation { cont in
            guard let stdin,
                  let data = try? JSONSerialization.data(withJSONObject: obj) else {
                cont.resume(returning: QueryResult(ok: false, error: "bridge not running", json: nil))
                return
            }
            resultConts[id] = cont
            var line = data
            line.append(0x0A)
            try? stdin.write(contentsOf: line)
        }
    }

    /// Called on every ``state`` frame (true = turn started, false = idle).
    /// Set by the facade to drive the thinking chip. Runs on the actor.
    var onState: (@Sendable (Bool) -> Void)?

    /// Called on every ``tool`` frame (name, phase ∈ start|done|error,
    /// elapsed). Drives the inline tool chips.
    var onTool: (@Sendable (String, String, Double) -> Void)?

    func setOnState(_ cb: @escaping @Sendable (Bool) -> Void) { onState = cb }
    func setOnTool(_ cb: @escaping @Sendable (String, String, Double) -> Void) {
        onTool = cb
    }

    /// Resolve the ``jaeger`` launcher. ``$JAEGER_BRIDGE_CMD`` overrides
    /// outright; else ``$JAEGER_REPO/jaeger``; else a dev-tree default.
    static func jaegerPath() -> String {
        let env = ProcessInfo.processInfo.environment
        if let cmd = env["JAEGER_BRIDGE_CMD"], !cmd.isEmpty { return cmd }
        let repo = (env["JAEGER_REPO"].flatMap { $0.isEmpty ? nil : $0 })
            ?? (NSHomeDirectory() as NSString).appendingPathComponent("GITHUB/JROS")
        return (repo as NSString).appendingPathComponent("jaeger")
    }

    /// Launch the bridge and await its ``ready`` frame (or ``fatal``).
    func start() async throws -> BridgeReady {
        guard process == nil else { throw BridgeError.launchFailed("already running") }

        let path = Self.jaegerPath()
        guard FileManager.default.isExecutableFile(atPath: path) else {
            throw BridgeError.launchFailed("\(path) not executable (set $JAEGER_REPO)")
        }

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: path)
        proc.arguments = ["bridge"]
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
            throw BridgeError.launchFailed(error.localizedDescription)
        }
        self.process = proc
        self.stdin = inPipe.fileHandleForWriting

        return try await withCheckedThrowingContinuation { cont in
            self.readyCont = cont
        }
    }

    /// Send one turn and await the agent's reply.
    func runTurn(_ text: String) async -> (text: String, error: String?) {
        guard process != nil else { return ("", "agent bridge not running") }
        write(["text": text])
        return await withCheckedContinuation { cont in
            self.replyCont = cont
        }
    }

    func stop() {
        write(["op": "quit"])
        process?.terminate()
        process = nil
        stdin = nil
        readyCont?.resume(throwing: BridgeError.notRunning)
        readyCont = nil
        replyCont?.resume(returning: ("", "bridge stopped"))
        replyCont = nil
    }

    // MARK: - internals

    private func ingest(_ data: Data) {
        for frame in framer.feed(data) {
            guard let f = Self.parse(frame) else { continue }
            switch f {
            case .ready(let instance, let model, let character, let icon):
                readyCont?.resume(returning: BridgeReady(
                    instance: instance, model: model, character: character, icon: icon))
                readyCont = nil
            case .result(let id, let ok, let error, let data):
                resultConts[id]?.resume(returning: QueryResult(ok: ok, error: error, json: data))
                resultConts[id] = nil
            case .state(let busy):
                onState?(busy)
            case .tool(let name, let phase, let elapsed):
                onTool?(name, phase, elapsed)
            case .reply(let text, let error):
                replyCont?.resume(returning: (text, error))
                replyCont = nil
            case .fatal(let error):
                readyCont?.resume(throwing: BridgeError.bootFailed(error))
                readyCont = nil
                replyCont?.resume(returning: ("", error))
                replyCont = nil
            }
        }
    }

    private func handleTermination() {
        readyCont?.resume(throwing: BridgeError.bootFailed("bridge exited"))
        readyCont = nil
        replyCont?.resume(returning: ("", "bridge exited"))
        replyCont = nil
        process = nil
        stdin = nil
    }

    private func write(_ obj: [String: Any]) {
        guard let stdin,
              var data = try? JSONSerialization.data(withJSONObject: obj)
        else { return }
        data.append(0x0A)
        try? stdin.write(contentsOf: data)
    }

    private enum Frame {
        case ready(instance: String, model: String?, character: String?, icon: String?)
        case result(id: String, ok: Bool, error: String?, data: Data?)
        case state(busy: Bool)
        case tool(name: String, phase: String, elapsed: Double)
        case reply(text: String, error: String?)
        case fatal(error: String)
    }

    private static func parse(_ frame: Data) -> Frame? {
        guard let obj = (try? JSONSerialization.jsonObject(with: frame))
                as? [String: Any],
              let type = obj["type"] as? String
        else { return nil }
        switch type {
        case "ready":
            return .ready(instance: obj["instance"] as? String ?? "",
                          model: obj["model"] as? String,
                          character: obj["character"] as? String,
                          icon: obj["icon"] as? String)
        case "result":
            var payload: Data? = nil
            if let d = obj["data"], !(d is NSNull) {
                payload = try? JSONSerialization.data(withJSONObject: d,
                                                      options: [.fragmentsAllowed])
            }
            return .result(id: obj["id"] as? String ?? "",
                           ok: obj["ok"] as? Bool ?? true,
                           error: obj["error"] as? String, data: payload)
        case "state":
            return .state(busy: obj["busy"] as? Bool ?? false)
        case "tool":
            return .tool(name: obj["name"] as? String ?? "",
                         phase: obj["phase"] as? String ?? "start",
                         elapsed: (obj["elapsed_s"] as? Double) ?? 0)
        case "reply":
            return .reply(text: obj["text"] as? String ?? "",
                          error: obj["error"] as? String)
        case "fatal":
            return .fatal(error: obj["error"] as? String ?? "bridge failed")
        default:
            return nil
        }
    }
}
