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
