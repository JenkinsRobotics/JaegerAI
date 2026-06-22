//
//  AgentBridge.swift
//  JaegerOS / Bridge
//
//  High-level agent client used everywhere except the transport itself
//  (the Chat window, the menu-bar status, the future Voice loop).  The
//  "agent" is gone: this now drives the out-of-process ``jaeger bridge``
//  child (see ``BridgeProcess``) — same typed surface, no socket.
//
//  @Observable-friendly so SwiftUI views watch ``isConnected`` / ``status``
//  without polling.  Shared singleton because the AppDelegate kicks off
//  ``tryConnect()`` at launch before SwiftUI's @StateObject wiring exists.
//

import Foundation

@MainActor
final class AgentBridge: ObservableObject {

    static let shared = AgentBridge()

    /// Reactive flag — drives the menu-bar icon swap + composer enable.
    @Published private(set) var isConnected: Bool = false

    /// Last-known agent status (instance + model), or nil while down.
    @Published private(set) var status: AgentStatus? = nil

    /// Last connect-failure reason, surfaced in the menu. Cleared on success.
    @Published private(set) var lastError: String? = nil

    /// Listeners for inline activity chips (thinking / tool). Driven off
    /// the bridge's ``state`` frames; tool events land when the bridge
    /// learns to emit them.
    private var listeners: [UUID: @MainActor (Event) -> Void] = [:]

    private var bridge: BridgeProcess?

    /// Default instance — honours ``JAEGER_INSTANCE_NAME`` (the bridge
    /// also resolves its own default, so this is just for display/parity).
    static var defaultInstanceName: String {
        ProcessInfo.processInfo.environment["JAEGER_INSTANCE_NAME"] ?? "default"
    }

    /// Diagnostic string for the About panel — the launcher we spawn.
    var socketPath: String? { BridgeProcess.jaegerPath() }

    /// Launch the bridge child and await its ready handshake.
    func connect(instance: String = defaultInstanceName) async throws {
        guard bridge == nil else { return }
        let proc = BridgeProcess()
        await proc.setOnState { [weak self] busy in
            Task { @MainActor in self?.fanout(state: busy) }
        }
        await proc.setOnTool { [weak self] name, phase, elapsed in
            Task { @MainActor in self?.fanout(tool: name, phase: phase, elapsed: elapsed) }
        }
        let ready = try await proc.start()
        bridge = proc
        isConnected = true
        lastError = nil
        status = AgentStatus(rawDict: [
            "instance": ready.instance,
            "model": ready.model as Any,
        ])
    }

    /// Connect without throwing — failures land on ``lastError``. The
    /// launch hook uses this (a missing bridge is the first-run state,
    /// not an exception).
    func tryConnect(instance: String = defaultInstanceName) async {
        do {
            try await connect(instance: instance)
            NSLog("[Bridge] connected — instance=\(status?.instance ?? "?")")
        } catch {
            lastError = error.localizedDescription
            NSLog("[Bridge] connect failed: \(error.localizedDescription)")
        }
    }

    func disconnect() async {
        if let bridge { await bridge.stop() }
        bridge = nil
        isConnected = false
        status = nil
    }

    /// Run one chat turn through the bridge; returns the reply text.
    func sendChat(text: String) async throws -> String {
        guard let bridge else { throw BridgeError.notRunning }
        let (reply, error) = await bridge.runTurn(text)
        if let error, !error.isEmpty { throw BridgeError.bootFailed(error) }
        return reply
    }

    // MARK: - Activity events

    /// Map a ``state`` frame onto the thinking-chip event vocabulary the
    /// chat view already understands.
    private func fanout(state busy: Bool) {
        let event = Event(name: busy ? "thinking" : "thought.end", payload: [:])
        for cb in listeners.values { cb(event) }
    }

    /// Map a ``tool`` frame onto the tool-chip event vocabulary
    /// ``ChatViewModel.handle`` already renders (tool.start / tool.complete).
    private func fanout(tool name: String, phase: String, elapsed: Double) {
        let evName = phase == "start" ? "tool.start" : "tool.complete"
        let event = Event(name: evName, payload: [
            "tool": AnyDecodable(name),
            "ok": AnyDecodable(phase != "error"),
            "elapsed_s": AnyDecodable(elapsed),
        ])
        for cb in listeners.values { cb(event) }
    }

    @discardableResult
    func addEventListener(_ callback: @escaping @MainActor (Event) -> Void) -> UUID {
        let id = UUID()
        listeners[id] = callback
        return id
    }

    func removeEventListener(_ id: UUID) {
        listeners.removeValue(forKey: id)
    }
}


// MARK: - AgentStatus

/// Snapshot of the agent's identity for the status row. Kept liberal so a
/// field rename can't crash the app.
struct AgentStatus {
    let rawDict: [String: Any]

    var instance: String? { rawDict["instance"] as? String }
    var modelName: String? { rawDict["model"] as? String }
    var uptimeSeconds: Double? { rawDict["uptime"] as? Double }
    var turnCount: Int? { rawDict["turns"] as? Int }

    /// The bridge only reports ``ready`` after the model loads, so by the
    /// time we have a status the agent is past booting.
    var isBooting: Bool { false }
}
