//
//  AgentBridge.swift
//  JaegerOS / Bridge
//
//  High-level agent client used everywhere except the transport itself
//  (the Chat window, the menu-bar status, the Voice loop). Drives the
//  out-of-process ``jaeger bridge`` child (see ``BridgeProcess``).
//
//  Phase-1 hardening (SWIFT_APP_ARCHITECTURE_PLAN.md): a real connection
//  STATE MACHINE (not a bool), a single in-flight connect, child-death
//  detection wired into published state, the agent lifecycle separated
//  from transport readiness (settings work while the model boots), and
//  interactive permission approval.
//
//  @Observable-friendly so SwiftUI views watch ``state`` / ``agentState``
//  / ``status`` without polling. ``isConnected`` remains as a computed
//  compatibility surface for existing views.
//

import AppKit
import Foundation

/// The transport connection, as a real state machine.
enum ConnectionState: Equatable {
    case disconnected
    case connecting
    case ready                 // transport up — queries/settings work
    case failed(String)        // connect failed (launch/boot/lock)
    case terminated(String)    // child died after being up

    var label: String {
        switch self {
        case .disconnected: return "stopped"
        case .connecting: return "connecting…"
        case .ready: return "running"
        case .failed(let m): return "failed: \(m)"
        case .terminated(let m): return m
        }
    }
}

@MainActor
final class AgentBridge: ObservableObject {

    static let shared = AgentBridge()

    /// Transport state — the machine, not a bool.
    @Published private(set) var state: ConnectionState = .disconnected

    /// Agent lifecycle, decoupled from the transport: the bridge is READY
    /// (settings usable) while the model is still ``booting``. The chat
    /// composer gates on ``agentState == .ready``.
    @Published private(set) var agentState: AgentLifecycle = .booting

    /// Compatibility surface — existing views read this.
    var isConnected: Bool { state == .ready }

    /// True from connect until the model finishes loading — drives
    /// "warming up" UI without blocking settings.
    var isAgentBooting: Bool {
        if case .booting = agentState { return true }
        return false
    }

    /// Last-known agent status (instance + model), or nil while down.
    @Published private(set) var status: AgentStatus? = nil

    /// True while a turn is running anywhere (any window, the pill…).
    /// Set from the bridge's ``state`` frames, so surfaces that exist
    /// independently of the chat window (tray card, orb) get the real
    /// busy signal without a view-to-view mirror.
    @Published private(set) var isBusy: Bool = false

    /// Last connect-failure reason, surfaced in the menu. Cleared on success.
    @Published private(set) var lastError: String? = nil

    /// First-run: the bridge reported ``fatal kind=no_instance`` — no
    /// agent exists on disk yet. The transport stays up (queries and the
    /// ``create_instance`` command work), and the onboarding window is
    /// presented over it. Cleared when onboarding finishes.
    @Published private(set) var needsOnboarding: Bool = false

    /// A pending permission request (published so a HUD can render it
    /// in-window later; the default presenter is an NSAlert).
    @Published private(set) var pendingRequest: BridgeRequest? = nil

    /// Listeners for inline activity chips (thinking / tool).
    private var listeners: [UUID: @MainActor (Event) -> Void] = [:]

    private var bridge: BridgeProcess?
    /// Single in-flight connect — a second caller awaits the same task
    /// instead of spawning a second child (the review's finding #3).
    private var connectTask: Task<Void, Error>?

    /// Default instance — honours ``JAEGER_INSTANCE_NAME`` (the bridge
    /// also resolves its own default, so this is just for display/parity).
    static var defaultInstanceName: String {
        ProcessInfo.processInfo.environment["JAEGER_INSTANCE_NAME"] ?? "default"
    }

    /// An EXPLICIT instance override, or nil to let the bridge resolve its
    /// own default. JaegerOS-dev.app pins ``jros-dev`` here via its
    /// Info.plist LSEnvironment; the product app leaves it unset.
    static var explicitInstance: String? {
        let v = ProcessInfo.processInfo.environment["JAEGER_INSTANCE_NAME"] ?? ""
        return v.isEmpty ? nil : v
    }

    /// Diagnostic string for the About panel — the launcher we spawn.
    var socketPath: String? { BridgeProcess.jaegerPath() }

    // MARK: - Connect / disconnect

    /// Launch the bridge child and await its (fast) ready handshake.
    /// Settings/queries are usable on return; the model may still be
    /// booting — watch ``agentState``.
    func connect(instance: String = defaultInstanceName) async throws {
        if state == .ready { return }
        if let inFlight = connectTask {          // join, don't double-spawn
            try await inFlight.value
            return
        }
        let task = Task { try await self.doConnect(instance: instance) }
        connectTask = task
        defer { connectTask = nil }
        try await task.value
    }

    private func doConnect(instance: String) async throws {
        state = .connecting
        agentState = .booting
        let proc = BridgeProcess()
        await proc.setOnState { [weak self] busy in
            Task { @MainActor in self?.fanout(state: busy) }
        }
        await proc.setOnTool { [weak self] name, phase, elapsed in
            Task { @MainActor in self?.fanout(tool: name, phase: phase, elapsed: elapsed) }
        }
        await proc.setOnAgentState { [weak self] lifecycle in
            Task { @MainActor in self?.handleAgentState(lifecycle) }
        }
        await proc.setOnRequest { [weak self] request in
            Task { @MainActor in self?.handleRequest(request) }
        }
        await proc.setOnFatal { [weak self] kind, error in
            Task { @MainActor in self?.handleFatal(kind: kind, error: error) }
        }
        await proc.setOnTermination { [weak self] clean in
            Task { @MainActor in self?.handleTermination(clean: clean) }
        }
        do {
            let ready = try await proc.start(instance: Self.explicitInstance)
            if ready.proto != ProtocolV1.version {
                await proc.stop()
                throw BridgeError.bootFailed(
                    "protocol mismatch: core speaks v\(ready.proto), "
                    + "shell speaks v\(ProtocolV1.version) — update JROS")
            }
            bridge = proc
            state = .ready
            lastError = nil
            if ready.agent == "ready" {          // already-warm core (attach)
                agentState = .ready(model: ready.model,
                                    character: ready.character, icon: ready.icon,
                                    agentName: ready.agentName)
            }
            status = AgentStatus(rawDict: [
                "instance": ready.instance,
                "model": ready.model as Any,
                "character": ready.character as Any,
                "icon": ready.icon as Any,
                "agent_name": ready.agentName as Any,
            ])
            // Attach-to-warm-core path: agent_state won't stream again,
            // so fetch the agent's name (identity.yaml) here.
            if ready.agent == "ready" {
                Task { await self.refreshIdentity() }
            }
        } catch {
            state = .failed(error.localizedDescription)
            throw error
        }
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
        state = .disconnected
        agentState = .booting
        status = nil
        isBusy = false
    }

    /// The Quit-from-tray path: give the core time to free the model and
    /// exit orderly (``bye``) before the app terminates. This is the ONLY
    /// place the agent's life ends — closing windows never reaches here.
    func shutdownForQuit() async {
        if let bridge { await bridge.quitGracefully() }
        bridge = nil
        state = .disconnected
        agentState = .booting
        status = nil
        isBusy = false
    }

    // MARK: - Queries / commands / chat

    /// Read-only data for the settings HUD (characters, config, permissions).
    func query(_ what: String, args: [String: any Sendable] = [:]) async -> QueryResult {
        guard let bridge else { return QueryResult(ok: false, error: "not connected", json: nil) }
        return await bridge.query(what, args: args)
    }

    /// A mutation (select/make-default/save…). Check ``ok``/``error``.
    /// A successful character switch re-reads the live identity so every
    /// surface bound to ``status`` (tray card, chat header, orb face)
    /// re-brands immediately — no restart, no next-boot wait.
    @discardableResult
    func command(_ cmd: String, args: [String: any Sendable] = [:]) async -> QueryResult {
        guard let bridge else { return QueryResult(ok: false, error: "not connected", json: nil) }
        let result = await bridge.command(cmd, args: args)
        if result.ok && cmd == "select_character" {
            await refreshIdentity()
        }
        return result
    }

    /// Re-ask the bridge for the agent name + active character + model and
    /// fold the answer into ``status``. Cheap (one small query); safe to
    /// call from any surface's appear hook. ``agent_name`` (v1 additive) is
    /// the AGENT's own name (identity.yaml) — surfaces lead with it; the
    /// character is the persona being played, secondary flavor.
    func refreshIdentity() async {
        let result = await query("identity")
        guard result.ok, let data = result.json,
              let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        else { return }
        var raw = status?.rawDict ?? [:]
        raw["agent_name"] = obj["agent_name"] as? String as Any
        raw["character"] = obj["character"] as? String as Any
        raw["icon"] = obj["icon"] as? String as Any
        if let model = obj["model"] as? String { raw["model"] = model as Any }
        status = AgentStatus(rawDict: raw)
    }

    /// Run one chat turn; returns the reply (text + optional telemetry:
    /// elapsed seconds and context usage, when the core sent them).
    /// ``session`` isolates this conversation on the Python side
    /// (sessions.db) so multiple windows / saved chats never collapse
    /// into one history.
    func sendChat(text: String, session: String = "desktop-app") async throws -> TurnResult {
        guard let bridge else { throw BridgeError.notRunning }
        let result = await bridge.runTurn(text, session: session)
        if let error = result.error, !error.isEmpty {
            throw BridgeError.bootFailed(error)
        }
        return result
    }

    // MARK: - Agent lifecycle + death detection

    private func handleAgentState(_ lifecycle: AgentLifecycle) {
        agentState = lifecycle
        if case .ready(let model, let character, let icon, let agentName) = lifecycle {
            // Enrich the status the fast handshake couldn't fill yet.
            var raw = status?.rawDict ?? [:]
            raw["model"] = model as Any
            raw["character"] = character as Any
            raw["icon"] = icon as Any
            if let agentName { raw["agent_name"] = agentName }
            status = AgentStatus(rawDict: raw)
            // Belt-and-suspenders: the frame now carries agent_name, but a
            // refresh also picks up any post-boot identity edit.
            Task { await self.refreshIdentity() }
        }
        if case .failed(let reason) = lifecycle {
            lastError = reason
        }
    }

    /// Route ``fatal`` frames by kind. ``no_instance`` is FIRST-RUN, not
    /// an error: the bridge transport stays alive for setup queries, so
    /// present the onboarding window instead of a failure surface.
    private func handleFatal(kind: String, error: String) {
        guard kind == "no_instance" else { return }
        needsOnboarding = true
        NSLog("[Bridge] no instance on disk — presenting onboarding")
        OnboardingWindowController.shared.show(agent: self)
    }

    /// Onboarding finished (instance created + agent booted): clear the
    /// first-run flag and refresh the identity every surface renders.
    func onboardingDidFinish() {
        needsOnboarding = false
        Task { await self.refreshIdentity() }
    }

    private func handleTermination(clean: Bool) {
        bridge = nil
        status = nil
        isBusy = false
        if clean {
            state = .disconnected
        } else {
            state = .terminated("agent process died")
            lastError = "agent process died unexpectedly"
        }
    }

    // MARK: - Permission requests

    /// Default presenter: a native alert. ``pendingRequest`` is also
    /// published so the settings HUD can render richer approval UI later
    /// without touching the transport.
    private func handleRequest(_ request: BridgeRequest) {
        pendingRequest = request
        guard request.kind == "approval" else { return }
        let alert = NSAlert()
        alert.messageText = "Jaeger asks permission"
        alert.informativeText = request.prompt
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Allow")
        alert.addButton(withTitle: "Deny")
        let allowed = alert.runModal() == .alertFirstButtonReturn
        respond(to: request, answer: allowed ? "allow" : "deny")
    }

    /// Answer a pending request (used by the alert above and available to
    /// any richer approval UI).
    func respond(to request: BridgeRequest, answer: String) {
        pendingRequest = nil
        guard let bridge else { return }
        Task { await bridge.respond(id: request.id, answer: answer) }
    }

    // MARK: - Activity events

    /// Map a ``state`` frame onto the thinking-chip event vocabulary the
    /// chat view already understands.
    private func fanout(state busy: Bool) {
        isBusy = busy
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
    /// The AGENT's own name — identity.yaml's ``name``, the unique robot
    /// named at instance creation (v1 additive ``agent_name`` off the
    /// identity query). Surfaces lead with this.
    var agentName: String? { rawDict["agent_name"] as? String }
    /// Active character's display name — the PERSONA being played,
    /// secondary flavor next to ``agentName`` ("Ted · playing HAL 9000").
    var character: String? { rawDict["character"] as? String }
    /// What the header should lead with: the agent's name, falling back
    /// to the character while the identity query is still in flight.
    var displayName: String? { agentName ?? character }
    /// Absolute path to the active character's profile image, if any.
    var iconPath: String? { rawDict["icon"] as? String }
    var uptimeSeconds: Double? { rawDict["uptime"] as? Double }
    var turnCount: Int? { rawDict["turns"] as? Int }
}
