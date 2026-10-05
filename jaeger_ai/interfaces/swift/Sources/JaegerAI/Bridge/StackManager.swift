//
//  StackManager.swift
//  JaegerAI / Bridge
//
//  Authoritative bridge to ``jaeger stack`` for whole-stack lifecycle:
//  - App open  -> stack up (all host services bootstrapped via launchd in ~/.jaeger/launchd/)
//  - App quit  -> stack down (bootout + hard kill verification of all stragglers)
//  - Reset     -> stack reset (down, up, and a REAL Gateway synthetic test turn verification)
//

import Foundation

struct StackServiceStatus: Decodable, Identifiable, Sendable {
    let id: String
    let name: String
    let label: String
    let pid: Int?
    let state: String
    let rawState: String?
    let ready: Bool
    let configured: Bool
    let port: Int?
    let gitCommit: String?
    let headCommit: String?
    let stale: Bool

    enum CodingKeys: String, CodingKey {
        case id, name, label, pid, state
        case rawState = "raw_state"
        case ready, configured, port
        case gitCommit = "git_commit"
        case headCommit = "head_commit"
        case stale
    }
}

struct StackStatusReply: Decodable, Sendable {
    let ok: Bool
    let services: [StackServiceStatus]
}

struct StackActionReply: Decodable, Sendable {
    let ok: Bool
    let step: String?
    let error: String?
    let services: [StackServiceStatus]?
}

final class StackManager: Sendable {
    static let shared = StackManager()

    /// Bring the whole stack up: plists generated into ~/.jaeger/launchd/, services bootstrapped
    func up(services: [String] = []) async throws -> StackActionReply {
        var args = ["stack", "up", "--json"]
        args.append(contentsOf: services)
        return try await runStackCommand(args)
    }

    /// Bring the whole stack down: bootout, wait, SIGKILL stragglers
    func down() async throws -> StackActionReply {
        return try await runStackCommand(["stack", "down", "--json"])
    }

    /// Reset: down, up, and verify with a real Gateway synthetic test turn
    func reset(timeout: Double = 60.0) async throws -> StackActionReply {
        return try await runStackCommand(["stack", "reset", "--timeout", "\(timeout)", "--json"])
    }

    /// Query live status of all services
    func status() async throws -> [StackServiceStatus] {
        let reply: StackStatusReply = try await runStackCommand(["stack", "status", "--json"])
        return reply.services
    }

    private func runStackCommand<T: Decodable & Sendable>(_ arguments: [String]) async throws -> T {
        try await Task.detached {
            let process = Process()
            let outputPipe = Pipe()
            let errorPipe = Pipe()
            process.executableURL = URL(fileURLWithPath: BridgeProcess.jaegerPath())
            process.arguments = arguments
            process.standardInput = FileHandle.nullDevice
            process.standardOutput = outputPipe
            process.standardError = errorPipe
            try process.run()
            let watchdog = Task {
                try? await Task.sleep(for: .seconds(120))
                if !Task.isCancelled && process.isRunning { process.terminate() }
            }
            defer { watchdog.cancel() }
            let data = outputPipe.fileHandleForReading.readDataToEndOfFile()
            let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            let stderr = String(data: errorData, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            guard !data.isEmpty else {
                let detail = stderr.isEmpty ? "Command exited with code \(process.terminationStatus)" : stderr
                throw NSError(domain: "JaegerStack", code: Int(process.terminationStatus), userInfo: [NSLocalizedDescriptionKey: detail])
            }
            return try JSONDecoder().decode(T.self, from: data)
        }.value
    }
}

/// The menu-bar process is the only lifecycle owner. It rewrites the lease
/// the Gateway and fabric supervisor already read. Workers must not call this.
enum LifecycleLeaseBeat {
    private static let queue = DispatchQueue(label: "ai.jaeger.lifecycle-lease")
    private static var timer: DispatchSourceTimer?
    private static let interval: TimeInterval = 5

    static func start() {
        queue.sync {
            guard timer == nil else { return }
            write()
            let source = DispatchSource.makeTimerSource(queue: queue)
            source.schedule(deadline: .now() + interval, repeating: interval)
            source.setEventHandler { write() }
            source.resume()
            timer = source
        }
    }

    static func stop() {
        queue.sync {
            timer?.setEventHandler {}
            timer?.cancel()
            timer = nil
        }
    }

    /// Quit path. A missing file means "no lease issued" and would allow
    /// privileged work, so the last beat is an already-expired menu-bar lease.
    /// Launchd KeepAlive cannot treat that as a live owner.
    static func retire() {
        queue.sync {
            timer?.setEventHandler {}
            timer?.cancel()
            timer = nil
            write(beatAt: 0)
        }
    }

    private static func environmentValue(_ key: String) -> String? {
        // ProcessInfo.environment is a launch snapshot. getenv sees JAEGER_*
        // set by the test harness and by anything that updates the process.
        guard let pointer = getenv(key) else { return nil }
        let value = String(cString: pointer).trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }

    private static func leaseURL() -> URL {
        if let raw = environmentValue("JAEGER_LIFECYCLE_LEASE") {
            return URL(fileURLWithPath: (raw as NSString).expandingTildeInPath)
        }
        let root: URL
        if let state = environmentValue("JAEGER_STATE_DIR") {
            root = URL(fileURLWithPath: (state as NSString).expandingTildeInPath)
        } else if let home = environmentValue("JAEGER_HOME") {
            root = URL(fileURLWithPath: (home as NSString).expandingTildeInPath).appendingPathComponent(".jaeger_ai")
        } else {
            root = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".jaeger")
        }
        return root.appendingPathComponent("control").appendingPathComponent("lifecycle-lease.json")
    }

    static func write(beatAt: TimeInterval? = nil) {
        let url = leaseURL()
        let directory = url.deletingLastPathComponent()
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let stamp = beatAt ?? Date().timeIntervalSince1970
            let body = String(format: "{\"beat_at\": %.6f, \"owner\": \"menubar\"}\n", stamp)
            try Data(body.utf8).write(to: url, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
        } catch {
            NSLog("[JaegerAI] lifecycle lease beat failed: \(error.localizedDescription)")
        }
    }
}
