//
//  ChatViewModel.swift
//  JaegerAI / ChatWindow
//
//  Holds the chat surface's mutable state and translates UI actions
//  (typing, hitting Enter) into agent calls.  The view itself stays
//  declarative; this is where the side-effects live.
//
//  Conversation state model:
//
//    * Each turn produces one ``ChatMessage`` from the user and
//      (eventually) one streaming ``ChatMessage`` from the assistant.
//    * Sync flow today (Week 2): the user message goes into the list,
//      we call ``chat.send`` over the socket, the response payload
//      lands as a single assistant bubble.  No streaming yet.
//    * Week 2.5 wires ``chat.subscribe`` events to render the
//      assistant bubble token-by-token like Hermes does (see
//      ``dev_docs/odysseus_review_and_0.3.0_plan.md`` for the
//      streaming UX target).
//

import Foundation
import SwiftUI

/// Composer execution mode — maps onto Jaeger's live execution axis.
enum OperatingMode: String, CaseIterable, Identifiable, Sendable {
    case ask = "Ask"
    case plan = "Plan"
    case agent = "Agent"

    var id: String { rawValue }

    /// Value sent to `/mode` on the bridge.
    var executionMode: String {
        switch self {
        case .ask: return "interactive"
        case .plan: return "supervised"
        case .agent: return "auto"
        }
    }

    var badgeText: String {
        switch self {
        case .ask: return "💬 Ask"
        case .plan: return "📋 Plan"
        case .agent: return "⚡ Agent"
        }
    }

    var summary: String {
        switch self {
        case .ask: return "Read-only Q&A — one turn, then the prompt comes back"
        case .plan: return "Architect first; every mutation pauses for approval"
        case .agent: return "Keeps executing until the job is done or you /stop"
        }
    }
}

/// One bubble in the transcript.  Carries the minimum the view needs;
/// the timestamp is preserved so a future log/export pass has it.
struct ChatMessage: Identifiable, Equatable {
    /// What kind of bubble this is.
    enum Author: Equatable {
        case user
        case assistant
        case system     // connection notices, errors, etc.
        case thinking   // live legacy indicator
        case toolCall   // live legacy tool line
        case thought    // persistent Claude Code style "⏱ Thought process >"
        case toolGroup  // persistent Claude Code style "Ran N commands >"
        case interactive // Clickable decision cards / option chips
    }

    let id: UUID
    let author: Author
    let timestamp: Date
    var text: String
    var isStreaming: Bool
    var meta: String?
    /// Gateway turn.finish / agents catalog identity for assistant rows.
    var displayName: String?
    var agentRole: String?
    var thoughtText: String
    var toolItems: [ToolCallItem]

    /// Compact chrome label, e.g. "Everyday · specialist".
    var agentLabel: String? {
        let name = (displayName ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let role = (agentRole ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if name.isEmpty { return nil }
        if role.isEmpty || role == "lead" { return name }
        return "\(name) · \(role)"
    }

    init(
        id: UUID = UUID(),
        author: Author,
        timestamp: Date = Date(),
        text: String = "",
        isStreaming: Bool = false,
        meta: String? = nil,
        displayName: String? = nil,
        agentRole: String? = nil,
        thoughtText: String = "",
        toolItems: [ToolCallItem] = []
    ) {
        self.id = id
        self.author = author
        self.timestamp = timestamp
        self.text = text
        self.isStreaming = isStreaming
        self.meta = meta
        self.displayName = displayName
        self.agentRole = agentRole
        self.thoughtText = thoughtText
        self.toolItems = toolItems
    }
}


/// One row in the History list — the bridge's ``list_sessions`` query
/// (``core/sessions.py`` SessionStore, most-active first). Keys match the
/// JSON verbatim (snake_case), same convention as ``SettingsStore``'s models.
struct SessionSummary: Codable, Identifiable, Equatable {
    let id: String
    let title: String?
    let preview: String?
    let created_at: Double?
    let last_active: Double
    let messages: Int

    /// Title if the operator (or a future rename feature) set one, else
    /// the first-user-line preview SessionStore records automatically,
    /// else a placeholder — never a blank row.
    var displayTitle: String {
        let t = (title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !t.isEmpty { return t }
        let p = (preview ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return p.isEmpty ? "(untitled)" : p
    }
}

/// One durable turn off ``load_session`` — ``core/sessions.py``
/// ``SessionStore.history``'s row shape.
struct SessionTurn: Codable, Equatable {
    let role: String
    let text: String
    let ts: Double
}

/// Owns the chat transcript + send pipeline.  One instance per chat
/// window; SwiftUI views observe it via ``@StateObject``.
@MainActor
final class ChatViewModel: ObservableObject {

    @Published private(set) var messages: [ChatMessage] = []

    /// True while a ``chat.send`` round-trip is in flight.  The
    /// composer's send button disables on this so the operator can't
    /// double-fire while we wait for the agent to reply.
    @Published private(set) var isSending: Bool = false
    @Published private(set) var controlledRequest: GatewayClient.RequestState?
    @Published private(set) var stopNotice: String?
    @Published private(set) var isStopping = false
    private var controlRefreshing = false
    private var controlRefreshingSession: String?
    private var controlRefreshWaiters: [CheckedContinuation<Bool, Never>] = []
    private var controlledSessionStatus: String?
    private var controlReadAvailable = false
    @Published private(set) var queuePausedByStop = false
    private var stopRequestedIDs: Set<String> = []
    private var resumedAfterStopIDs: Set<String> = []
    private let controlGateway: any SessionControlClient

    var hasActiveTurn: Bool {
        isSending || (controlledRequest?.session_id == sessionKey && controlledRequest?.isActive == true) ||
            (sessionKey == "dispatcher" && dispatcherRun?.active == true)
    }

    var canStopTurn: Bool {
        if isStopping { return false }
        if sessionKey == "dispatcher" {
            guard let run = dispatcherRun else { return false }
            return run.active == true && run.status != "cancelling" &&
                !stopRequestedIDs.contains("dispatcher:" + run.run_id)
        }
        guard controlReadAvailable, let request = controlledRequest, request.session_id == sessionKey else { return false }
        return request.canCancel && !stopRequestedIDs.contains(request.request_id)
    }

    var turnControlLabel: String {
        if sessionKey == "dispatcher" { return dispatcherStatus }
        return stopNotice ?? controlledRequest?.stopLabel ?? (isSending ? "Finding current request…" : "")
    }

    /// The server is the authority even when this window did not send the turn.
    @discardableResult
    func refreshTurnControl() async -> Bool {
        if sessionKey == "dispatcher" { return await refreshDispatcher() }
        let selected = sessionKey
        if controlRefreshing {
            let observedSession = controlRefreshingSession
            let succeeded = await withCheckedContinuation { controlRefreshWaiters.append($0) }
            guard selected == sessionKey else { return false }
            if observedSession != selected { return await refreshTurnControl() }
            return succeeded
        }
        controlRefreshing = true
        controlRefreshingSession = selected
        var succeeded = false
        defer {
            controlRefreshing = false
            let waiters = controlRefreshWaiters
            controlRefreshWaiters.removeAll()
            for waiter in waiters { waiter.resume(returning: succeeded) }
        }
        do {
            let session = try await controlGateway.getSessionControl(id: selected)
            guard selected == sessionKey else { return false }
            controlReadAvailable = true
            controlledSessionStatus = session.status
            var observed = session.latest_request
            if observed?.request_id == controlledRequest?.request_id, observed?.error == nil {
                observed?.error = controlledRequest?.error
            }
            controlledRequest = observed
            recoveredApprovalState.observeControl(session: selected, request: controlledRequest,
                stopRequested: controlledRequest.map { stopRequestedIDs.contains($0.request_id) } ?? false)
            if let request = controlledRequest, request.status == "cancelling" ||
                request.status == "cancelled" || request.status == "execution_unknown" {
                if !resumedAfterStopIDs.contains(request.request_id) { queuePausedByStop = true }
                stopNotice = request.stopLabel
            } else if let request = controlledRequest, request.isActive, stopRequestedIDs.contains(request.request_id) {
                stopNotice = "Stop unconfirmed — waiting for backend observation; cancellation will not be resent"
            } else if !isStopping {
                stopNotice = controlledRequest?.status == "failed" ? controlledRequest?.stopLabel : nil
            }
            if session.status == "running" && controlledRequest == nil {
                stopNotice = "Current request identity unavailable — update Gateway before using scoped Stop"
            }
            succeeded = true
            return true
        } catch {
            guard selected == sessionKey else { return false }
            controlReadAvailable = false
            if let failure = error as? GatewayClient.Failure, failure.statusCode == 404,
               !isSending, controlledRequest == nil, messages.isEmpty {
                stopNotice = nil // A new unsent conversation has no request to stop.
                return false
            }
            stopNotice = "Stop status unavailable — work may still be running. " + error.localizedDescription
            return false
        }
    }

    /// The bridge owns local text streaming; read its Gateway activity without
    /// replacing that transcript or extending the Stop preflight.
    func refreshConversationActivity() async {
        let selected = sessionKey, generation = selectionGeneration
        guard localTurnSession == selected else { return }
        guard let snapshot = try? await recoveryGateway.conversationSnapshot(id: selected),
              selected == sessionKey, generation == selectionGeneration,
              localTurnSession == selected, snapshot.session_id == selected else { return }
        conversationActivity = snapshot.activity_context ?? []
    }

    /// Capture the displayed target synchronously in the button callback.
    func requestStopCurrentTurn() {
        let selected = sessionKey
        let displayed = controlledRequest
        recoveredApprovalState.invalidateForStop(session: selected, requestID: displayed?.request_id)
        if selected == "dispatcher" { controlDispatcher("cancel"); return }
        Task { await stopTurn(displayed: displayed, selected: selected) }
    }

    func stopCurrentTurn() async {
        let selected = sessionKey
        let displayed = controlledRequest
        recoveredApprovalState.invalidateForStop(session: selected, requestID: displayed?.request_id)
        if selected == "dispatcher" { controlDispatcher("cancel"); return }
        await stopTurn(displayed: displayed, selected: selected)
    }

    private func stopTurn(displayed: GatewayClient.RequestState?, selected: String) async {
        guard !isStopping, selected == sessionKey else { return }
        TTSManager.shared.stop()
        queuePausedByStop = true
        guard let target = displayed, target.session_id == selected, target.canCancel else {
            stopNotice = displayed?.stopLabel ?? "Cannot stop: no authoritative displayed request identity"
            return
        }
        guard !stopRequestedIDs.contains(target.request_id) else {
            stopNotice = "Stop already requested — refresh to observe the outcome"
            return
        }
        isStopping = true
        defer { isStopping = false }
        do {
            let observed = try await controlGateway.getSessionControl(id: selected)
            guard selected == sessionKey else { return }
            controlledRequest = observed.latest_request
            controlReadAvailable = true
            guard let current = observed.latest_request,
                  current.session_id == target.session_id,
                  current.request_id == target.request_id else {
                stopNotice = "Displayed request changed — successor was not stopped"
                return
            }
            guard current.canCancel else { stopNotice = current.stopLabel; return }
            stopRequestedIDs.insert(target.request_id)
            recoveredApprovalState.clear()
            stopNotice = "Requesting cancellation…"
            let receipt = try await controlGateway.cancelTurn(sessionID: target.session_id, requestID: target.request_id)
            guard selected == sessionKey, controlledRequest?.request_id == target.request_id else { return }
            controlledRequest = receipt
            stopNotice = receipt.stopLabel
        } catch {
            guard selected == sessionKey, controlledRequest?.request_id == target.request_id else { return }
            stopNotice = "Stop unconfirmed — refresh to observe this request. " + error.localizedDescription
        }
    }

    private var queueControlAvailable: Bool {
        sessionKey == "dispatcher" ? dispatcherConnected : controlReadAvailable
    }

    private var queueOutcomeUnknown: Bool {
        if sessionKey == "dispatcher" {
            guard let run = dispatcherRun else { return uncertainDispatcherRequest != nil }
            return uncertainDispatcherRequest != nil || run.execution_unknown == true ||
                ["interrupted", "execution_unknown", "unknown"].contains(run.status) ||
                (run.active != true && !["completed", "failed", "cancelled"].contains(run.status))
        }
        if let request = controlledRequest,
           !request.isActive && !["completed", "failed", "cancelled"].contains(request.status) { return true }
        return controlledRequest?.status == "execution_unknown" || controlledSessionStatus == "execution_unknown" ||
            (controlledRequest == nil && ["running", "cancelling"].contains(controlledSessionStatus ?? ""))
    }

    var canResumeQueue: Bool {
        queuePausedByStop && localTurnSession == nil && !hasActiveTurn && queueControlAvailable && !queueOutcomeUnknown &&
            pendingSends.contains { $0.sessionID == sessionKey }
    }

    /// Only this explicit action resumes retained follow-ups after Stop.
    func resumeQueuedMessages() async {
        guard await refreshTurnControl() else { return }
        guard canResumeQueue else { return }
        if sessionKey == "dispatcher", let run = dispatcherRun {
            resumedAfterStopIDs.insert("dispatcher:" + run.run_id)
        } else if let requestID = controlledRequest?.request_id {
            resumedAfterStopIDs.insert(requestID)
        }
        queuePausedByStop = false
        await drainQueuedMessages()
    }

    func drainQueuedMessages() async {
        while !Task.isCancelled {
            guard await refreshTurnControl() else { return }
            guard !Task.isCancelled, localTurnSession == nil, !queuePausedByStop, !hasActiveTurn, queueControlAvailable, !queueOutcomeUnknown,
                  let index = pendingSends.firstIndex(where: { $0.sessionID == sessionKey }) else { return }
            let next = pendingSends.remove(at: index)
            _ = await runTurn(next.prompt, appendUserBubble: false, displayText: next.display,
                              images: next.images, useTools: next.agenticTools)
        }
    }



    /// The answer row of the turn currently running.
    ///
    /// It is appended when the turn starts and stays pinned to the bottom:
    /// ``TranscriptFeed`` inserts every thought and tool run ABOVE it, so
    /// the reply the operator asked for is always the last thing in the
    /// turn. Held as an id rather than an index because activity rows
    /// inserted above it shift its position on nearly every event.
    let recoveredApprovalState: RecoveredApprovalState
    private var selectionGeneration = UUID()
    private var localTurnSession: String?
    private var recoveryTask: Task<Void, Never>?
    private let recoveryGateway: any ChatRecoveryClient
    @Published private(set) var recoveryNotice: String?
    @Published private(set) var conversationActivity: [GatewayClient.ConversationSnapshot.Activity] = []
    @Published private(set) var conversationError: String?

    private var answerID: UUID?

    /// 0.8.1 item 9: messages typed while a turn is already in flight.
    /// The bridge's own turn queue (a FIFO ``queue.Queue``, see
    /// ``interfaces/bridge.py``) never drops a mid-turn send either —
    /// but ``BridgeProcess`` only tracks ONE in-flight reply
    /// continuation, so this client can't fire two turns at once
    /// without redesigning that. Queueing locally and draining in
    /// ``send`` fixes the actual bug (a mid-turn Return silently
    /// cleared the composer and dropped the text — see ``send``'s old
    /// ``guard !isSending else { return }``) without touching the
    /// bridge's concurrency model. ``count`` lets a view show "queued".
    struct PendingSend {
        let sessionID: String
        let prompt: String
        let display: String
        let images: [String]
        let agenticTools: Bool
    }
    @Published private(set) var pendingSends: [PendingSend] = []

    /// Composer text — bound to the chat window's TextField.  Owned
    /// by the view-model so transcription results (from STT) can
    /// drop straight into it without needing a callback up to the
    /// view.  The view does ``$chat.composerText`` for the binding.
    @Published var agenticTools: Bool = true

    @Published var composerText: String = ""

    /// True while a STT pass is running.  Disables the send button,
    /// shows a "transcribing…" indicator in the status bar.
    @Published private(set) var isTranscribing: Bool = false

    /// True only while macOS is resolving the explicit microphone request.
    /// Keeping this distinct from recording avoids making a slow TCC prompt
    /// look like a dead button.
    @Published private(set) var isRequestingMicrophone: Bool = false

    /// Context usage after the most recent reply — ``(used, max)`` tokens
    /// off the reply frame's v1 telemetry.  Rendered in the status bar as
    /// "ctx 18.3K/32.8K"; nil until the first telemetry-carrying reply.
    @Published private(set) var contextUsage: (used: Int, max: Int)? = nil

    /// The instance's ``display.activity_trace`` setting (config.yaml,
    /// read over the bridge) — what becomes of the tool/thought chips:
    ///   "full"    keep them under the turn (default)
    ///   "summary" collapse to "N steps · " on the reply's meta line
    ///   "clear"   show live, remove when the reply lands
    ///   "off"     never show them
    @Published private(set) var activityTrace: String = "full"

    /// ``display.turn_separators`` — the thin accent rule between turns.
    @Published private(set) var turnSeparators: Bool = true

    /// The session key the agent uses to scope rolling history (the
    /// sessions.db row this window's turns land in). Mutable — "New Chat"
    /// mints a fresh key, and picking a conversation from History adopts
    /// THAT session's id — so both change it mid-window-lifetime instead
    /// of forcing a new ``ChatViewModel``.
    @Published private(set) var sessionKey: String

    /// True while a History fetch / session switch is in flight — gates
    /// the History button/list so the operator can't double-fire.
    @Published private(set) var isSwitchingSession: Bool = false

    /// Hermes-style ``/model`` overlay. Set by ``send`` when the operator
    /// types a bare ``/model`` / ``/models``; the chat view presents the
    /// clickable picker instead of dumping a catalogue into the transcript.
    @Published var showModelPicker: Bool = false

    /// The agent's current operating mode (Ask, Plan, Agent).
    @Published var operatingMode: OperatingMode = .ask
    @Published private(set) var isSwitchingOperatingMode: Bool = false

    func setOperatingMode(_ mode: OperatingMode) {
        Task { await dispatchExecutionMode(mode) }
    }

    /// `/mode <execution>` hits the bridge slash registry so this is a
    /// real process-global switch, not a local transcript bubble.
    private func dispatchExecutionMode(_ mode: OperatingMode) async {
        guard !isSwitchingOperatingMode else { return }
        isSwitchingOperatingMode = true
        defer { isSwitchingOperatingMode = false }
        let acknowledged = await runTurn(
            "/mode \(mode.executionMode)",
            appendUserBubble: false,
            displayText: nil
        )
        if acknowledged {
            operatingMode = mode
            appendSystem("\(mode.badgeText) — \(mode.summary)")
        } else {
            appendSystem("⚠ Mode change was not acknowledged; still \(operatingMode.badgeText).")
        }
    }

    @Published private(set) var dispatcherConnected = false
    @Published private(set) var dispatcherStatus = "Connecting to Dispatcher…"
    @Published private(set) var dispatcherApproval: BridgeRequest?
    @Published private(set) var dispatcherReports: [DispatcherClient.Report] = []
    @Published private(set) var dispatcherRun: DispatcherClient.Run?
    private var dispatcherClient: (any DispatcherConversationClient)?
    private let dispatcherClientOverride: (any DispatcherConversationClient)?
    private var messageIDs: [String: UUID] = [:]
    private var answeringApprovalID: String?
    private var dispatcherSending = false
    private var uncertainDispatcherRequest: (text: String, id: String)?
    private var dispatcherRefreshing = false
    private var dispatcherRefreshWaiters: [CheckedContinuation<Bool, Never>] = []

    private func connectedDispatcher() async throws -> any DispatcherConversationClient {
        if let dispatcherClientOverride { return dispatcherClientOverride }
        if !agent.isConnected { await agent.tryConnect() }
        if let client = dispatcherClient { return client }
        let result = await agent.query("dispatcher_connection")
        guard result.ok, let data = result.json,
              let object = try JSONSerialization.jsonObject(with: data) as? [String: String],
              let base = object["base_url"], let url = URL(string: base),
              let key = object["api_key"] else {
            throw DispatcherClient.Failure(message: "Connect the Jaeger instance and its profile gateway first")
        }
        let client = DispatcherClient(baseURL: url, apiKey: key)
        dispatcherClient = client
        return client
    }

    @discardableResult
    func refreshDispatcher() async -> Bool {
        guard sessionKey == "dispatcher" else { return false }
        if dispatcherRefreshing {
            let succeeded = await withCheckedContinuation { dispatcherRefreshWaiters.append($0) }
            return succeeded && sessionKey == "dispatcher"
        }
        dispatcherRefreshing = true
        var succeeded = false
        defer {
            dispatcherRefreshing = false
            let waiters = dispatcherRefreshWaiters
            dispatcherRefreshWaiters.removeAll()
            for waiter in waiters { waiter.resume(returning: succeeded) }
        }
        do {
            let client = try await connectedDispatcher()
            let snapshot = try await client.snapshot()
            guard sessionKey == "dispatcher" else { return false }
            dispatcherRun = snapshot.run
            if let run = snapshot.run,
               ["cancelling", "cancelled", "interrupted", "execution_unknown"].contains(run.status) || run.execution_unknown == true {
                if !resumedAfterStopIDs.contains("dispatcher:" + run.run_id) { queuePausedByStop = true }
            }
            dispatcherReports = snapshot.reports ?? []
            dispatcherConnected = true
            if let run = snapshot.run, run.status != "completed" {
                dispatcherStatus = "Dispatcher — " + run.status + (run.error.map { ": " + $0 } ?? "")
            } else { dispatcherStatus = "Dispatcher · synced with WebUI" }
            var rows = snapshot.messages.map { row -> ChatMessage in
                let id = messageIDs[row.id] ?? UUID()
                messageIDs[row.id] = id
                return ChatMessage(id: id, author: row.role == "user" ? .user : .assistant,
                                   timestamp: Date(timeIntervalSince1970: row.ts), text: row.text)
            }
            if let run = snapshot.run, run.active == true, !run.output.isEmpty {
                let key = "run-" + run.run_id
                let id = messageIDs[key] ?? UUID(); messageIDs[key] = id
                rows.append(ChatMessage(id: id, author: .assistant, text: run.output, isStreaming: true))
            }
            messages = rows
            if let request = snapshot.run?.approvals?.first, request.approval_id != answeringApprovalID {
                dispatcherApproval = BridgeRequest(id: request.approval_id, kind: "approval",
                                                   prompt: request.description, options: request.choices)
            } else { dispatcherApproval = nil }
            succeeded = true
            return true
        } catch {
            guard sessionKey == "dispatcher" else { return false }
            dispatcherClient = nil
            dispatcherConnected = false
            dispatcherStatus = "Connection unavailable — \(error.localizedDescription)"
            return false
        }
    }

    func controlDispatcher(_ action: String, approval: BridgeRequest? = nil, choice: String? = nil) {
        guard let run = dispatcherRun else { return }
        if action == "cancel" {
            queuePausedByStop = true
            TTSManager.shared.stop()
            let key = "dispatcher:" + run.run_id
            guard !stopRequestedIDs.contains(key) else { return }
            stopRequestedIDs.insert(key)
        }
        if let approval, action == "approval" {
            guard answeringApprovalID != approval.id else { return }
            answeringApprovalID = approval.id
            dispatcherApproval = nil // Dismissing the sheet must not send a second "deny".
        }
        Task {
            defer { if action == "approval" { answeringApprovalID = nil } }
            do {
                let client = try await connectedDispatcher()
                var body = ["run_id": run.run_id]
                if let approval { body["approval_id"] = approval.id; body["choice"] = choice }
                _ = try await client.request(action, body: body)
                await refreshDispatcher()
            } catch { dispatcherStatus = error.localizedDescription }
        }
    }

    private func sendDispatcher(_ text: String) async -> Bool {
        guard !dispatcherSending else { return false }
        dispatcherSending = true
        isSending = true
        defer {
            dispatcherSending = false
            if sessionKey == "dispatcher", localTurnSession == nil { isSending = false }
        }
        let requestID = uncertainDispatcherRequest?.text == text
            ? uncertainDispatcherRequest!.id
            : UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        uncertainDispatcherRequest = (text, requestID)
        do {
            let client = try await connectedDispatcher()
            let run = try await client.send(text, requestID: requestID)
            uncertainDispatcherRequest = nil
            if ["completed", "failed", "cancelled", "interrupted"].contains(run.status) {
                await refreshDispatcher()
                return run.status == "completed"
            }
            repeat {
                await refreshDispatcher()
                if dispatcherRun?.run_id == run.run_id, dispatcherRun?.active != true { break }
                if dispatcherStatus.hasPrefix("Connection unavailable") {
                    dispatcherStatus += ". Work was not resubmitted; reconnect to observe it."
                    return false
                }
                try await Task.sleep(for: .seconds(1))
            } while sessionKey == "dispatcher"
            let completed = dispatcherRun?.status == "completed"
            if completed, sessionKey == "dispatcher", TTSManager.shared.autoSpeakEnabled,
               let output = dispatcherRun?.output, !output.isEmpty {
                TTSManager.shared.speak(output)
            }
            return completed
        } catch {
            NSLog("[ChatViewModel] sendDispatcher failed (\(error.localizedDescription)) — no resubmission")
            dispatcherStatus = "Dispatcher unavailable — submission outcome unconfirmed; reconnect to observe it. " + error.localizedDescription
            return false
        }
    }

    private let agent: AgentBridge
    private var eventToken: UUID?

    /// Push-to-talk recorder.  Owned by the view-model so the same
    /// instance survives across composer interactions; the view binds
    /// to its ``@Published`` state for the level meter + recording
    /// indicator.  Week 4 wires the captured audio into a
    /// ``transcribe`` round-trip; Week 5 swaps in CoreML Whisper.
    let voice = VoiceRecorder()

    /// A fresh per-launch key ("desktop-app" used to be shared by every
    /// window/relaunch, so every conversation merged into one sessions.db
    /// row — see runway item 4). Short, matching the PySide6 window's own
    /// ``uuid.uuid4().hex[:8]`` convention (rich_tui/window.py).
    nonisolated static func mintSessionKey() -> String {
        UUID().uuidString.replacingOccurrences(of: "-", with: "")
            .lowercased().prefix(8).description
    }

    init(agent: AgentBridge, sessionKey: String = ChatViewModel.mintSessionKey(),
         controlGateway: any SessionControlClient = GatewayClient.fromEnvironment(),
         startBackgroundObservers: Bool = true,
         dispatcherClient: (any DispatcherConversationClient)? = nil,
         recoveryGateway: any ChatRecoveryClient = GatewayClient.fromEnvironment(),
         recoveredApprovalState: RecoveredApprovalState? = nil) {
        self.agent = agent
        self.recoveredApprovalState = recoveredApprovalState ?? RecoveredApprovalState()
        self.sessionKey = sessionKey
        self.recoveryGateway = recoveryGateway
        self.controlGateway = controlGateway
        self.dispatcherClientOverride = dispatcherClient
        guard startBackgroundObservers else { return }
        // Subscribe to agent events so we can show thinking + tool
        // chips inline as the agent works.  Captures a weak self so
        // we don't pin the view model alive past the chat window's
        // lifetime.
        self.eventToken = agent.addEventListener { [weak self] event in
            self?.handle(event: event)
        }
        // Pull the instance's display prefs (activity_trace + separators)
        // once the transport is up. Best-effort — defaults stand on a miss.
        Task { [weak self] in await self?.loadDisplayConfig() }
        Task { [weak self] in
            while !Task.isCancelled {
                guard let self, self.sessionKey == "dispatcher" else {
                    try? await Task.sleep(for: .seconds(2))
                    continue
                }
                await self.refreshDispatcher()
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    /// True once a config query has answered — used to retry the read on
    /// the first send when the init-time fetch raced the connect.
    private var displayConfigLoaded = false

    /// Read ``display.*`` prefs over the bridge's config query. Public so a
    /// future settings surface can re-call it after a save_config.
    func loadDisplayConfig() async {
        let result = await agent.query("config")
        guard result.ok, let data = result.json,
              let obj = (try? JSONSerialization.jsonObject(with: data))
                as? [String: Any]
        else { return }
        displayConfigLoaded = true
        if let trace = obj["activity_trace"] as? String, !trace.isEmpty {
            activityTrace = trace
        }
        if let sep = obj["turn_separators"] as? Bool {
            turnSeparators = sep
        }
    }

    // MARK: - Voice

    /// Start push-to-talk capture.  Synchronous — see VoiceRecorder
    /// for why we avoid Task-hops in this path.
    func startVoice() {
        guard !voice.isRecording, !isRequestingMicrophone else { return }
        guard VoiceRecorder.hasAudioInput else {
            appendSystem(
                "voice unavailable — macOS reports no audio input device. "
                + "Connect a USB, Bluetooth, display, or Continuity microphone."
            )
            return
        }
        isRequestingMicrophone = true
        Task { [weak self] in
            guard let self else { return }
            let granted = await VoiceRecorder.requestMicrophoneAccess()
            self.isRequestingMicrophone = false
            guard granted else {
                self.appendSystem(
                    "voice unavailable — allow JaegerAI under System Settings "
                    + "→ Privacy & Security → Microphone."
                )
                return
            }
            do {
                try self.voice.startRecording()
            } catch {
                self.appendSystem("voice unavailable — \(error.localizedDescription)")
            }
        }
    }

    /// Stop push-to-talk capture and hand the buffer to the STT
    /// manager.  Transcription lands in ``composerText`` so the
    /// operator can review / edit before sending — same flow Apple
    /// Notes uses for voice dictation, lower stakes than auto-
    /// submitting to the agent.  A system bubble notes capture
    /// duration + which backend ran for telemetry.
    private var transcriptionGeneration = 0

    func stopVoice(autoSend: Bool = false) {
        transcriptionGeneration += 1
        let transcription = transcriptionGeneration
        let selected = sessionKey
        let generation = selectionGeneration
        voice.stopRecording()
        guard let captured = voice.takeCapturedAudio() else { return }
        let sampleRate = captured.format.sampleRate
        let seconds = Double(captured.samples.count) / sampleRate
        let backendName = "Jaeger Whisper medium.en"

        // Skip very short captures — usually accidental taps.
        guard seconds >= 0.4 else {
            appendSystem(String(
                format: "🎙 captured %.1fs · too short to transcribe",
                seconds
            ))
            return
        }

        appendSystem(String(
            format: "🎙 captured %.1fs · transcribing via %@…",
            seconds, backendName
        ))
        isTranscribing = true
        let pcm = captured.samples.withUnsafeBufferPointer { pointer -> Data in
            guard let base = pointer.baseAddress else { return Data() }
            return Data(bytes: base, count: pointer.count * MemoryLayout<Float>.size)
        }
        Task { [weak self] in
            guard let self else { return }
            let result = await self.agent.command(
                "transcribe_audio",
                args: [
                    "pcm_f32le": pcm.base64EncodedString(),
                    "sample_rate": sampleRate,
                    "model": "medium.en",
                ],
                timeout: .seconds(90)
            )
            guard transcription == self.transcriptionGeneration else { return }
            self.isTranscribing = false
            guard selected == self.sessionKey, generation == self.selectionGeneration else { return }
            guard result.ok, let data = result.json,
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let text = object["text"] as? String, !text.isEmpty else {
                self.appendSystem(
                    "⚠ transcription failed — \(result.error ?? "no speech detected")"
                )
                return
            }
            let elapsed = object["elapsed_seconds"] as? Double ?? 0
            if autoSend {
                self.appendSystem(String(
                    format: "✓ heard in %.1fs · sending voice turn", elapsed
                ))
                await self.send(text)
            } else {
                if self.composerText.isEmpty { self.composerText = text }
                else { self.composerText += " " + text }
                self.appendSystem(String(
                    format: "✓ transcribed in %.1fs · review and hit send", elapsed
                ))
            }
        }
    }

    deinit {
        recoveryTask?.cancel()
        if let token = eventToken {
            // ``deinit`` can't be @MainActor; agent's removeListener
            // is.  Dispatch back to main so we don't tear down on a
            // background queue.
            let d = agent
            Task { @MainActor in d.removeEventListener(token) }
        }
    }

    /// Push a system message into the transcript.  Used for connection
    /// errors, "agent booting", etc.  Not sent over the wire.
    func appendSystem(_ text: String) {
        messages.append(ChatMessage(
            author: .system,
            timestamp: Date(),
            text: text
        ))
    }

    /// Translate a agent Event into an inline chip.  Best-effort —
    /// the agent publishes a moving target of event names and we
    /// don't want to crash the UI over an unrecognised one.  Known
    /// names get pretty chips; unknowns fall through silently (they
    /// still show up in NSLog for diagnostics).
    private func handle(event: Event) {
        guard sessionKey != "dispatcher", localTurnSession == sessionKey, isSending else { return }
        switch event.name {
        case "subscribed":
            // The "we're listening now" handshake.  Don't display.
            return
        case "turn.start":
            return
        case "turn.end":
            TranscriptFeed.closeStreaming(in: &messages)
            return
        case "thought.start", "deep_think.start", "thinking", "thought.delta", "thought":
            guard activityTrace != "off" else { return }
            let text = event.payload["text"]?.get(String.self)
                ?? event.payload["thought"]?.get(String.self)
                ?? event.payload["delta"]?.get(String.self)
                ?? ""
            TranscriptFeed.appendThought(text, to: &messages, answerID: answerID)
        case "thought.end", "deep_think.end":
            TranscriptFeed.closeThought(in: &messages, answerID: answerID)
        case "tool.call", "tool.start":
            guard activityTrace != "off" else { return }
            let name = event.payload["tool"]?.get(String.self)
                ?? event.payload["name"]?.get(String.self)
                ?? "tool"
            if name == "work_ledger" { return }
            let detail = event.payload["detail"]?.get(String.self) ?? ""
            TranscriptFeed.beginTool(
                ToolCallItem(name: name, detail: detail, isStreaming: true),
                in: &messages, answerID: answerID)
        case "tool.result", "tool.end", "tool.complete":
            TranscriptFeed.completeTool(
                ok: event.payload["ok"]?.get(Bool.self) ?? true,
                elapsed: event.payload["elapsed_s"]?.get(Double.self) ?? 0,
                in: &messages, answerID: answerID)
        case "task.progress":
            // Owned by ``AgentBridge.taskProgress`` (the chat drawer and
            // the ⌥Space HUD). Don't turn ledger ticks into tool chips.
            return
        case "token", "message.delta":
            let delta = event.payload["text"]?.get(String.self)
                ?? event.payload["delta"]?.get(String.self)
                ?? ""
            TranscriptFeed.appendAnswerDelta(delta, to: &messages, answerID: answerID)
        default:
            return
        }
    }

    /// Send a user turn through the agent's ``chat.send`` verb.
    func send(_ text: String, imageDataURIs: [String] = []) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        // Stop in-flight speech playback immediately when user sends a new message or command
        TTSManager.shared.stop()

        switch SlashRouting.action(for: trimmed) {
        case .modelPicker:
            showModelPicker = true
            return
        case .modelUse(let provider, let model):
            await applyTypedModelUse(provider: provider, model: model)
            return
        case .newChat:
            await newChat()
            return
        case .stop:
            TTSManager.shared.stop()
            await stopCurrentTurn()
            return
        case .steer(let guidance):
            agent.steer(guidance)
            appendSystem("steered: \(guidance)")
            return
        case .local(let notice):
            appendSystem(notice)
            return
        case .chat(let prompt, let display):
            await enqueueOrRun(prompt, display: display, images: imageDataURIs)
        case .passThrough:
            await enqueueOrRun(trimmed, display: trimmed, images: imageDataURIs)
        }
    }

    /// Queue behind an in-flight turn, or run immediately.
    private func enqueueOrRun(_ prompt: String, display: String, images: [String]) async {
        if hasActiveTurn || localTurnSession != nil {
            if let localTurnSession, localTurnSession != sessionKey { queuePausedByStop = true }
            pendingSends.append(PendingSend(sessionID: sessionKey, prompt: prompt, display: display, images: images, agenticTools: agenticTools))
            messages.append(ChatMessage(
                author: .user, timestamp: Date(), text: display))
            return
        }
        let selected = sessionKey
        let succeeded = await runTurn(prompt, appendUserBubble: true, displayText: display, images: images, useTools: agenticTools)
        guard selected == sessionKey else { return }
        if sessionKey == "dispatcher" && !succeeded { queuePausedByStop = true; return }
        await drainQueuedMessages()
    }

    /// Direct ``/model use <provider> <name>`` — no picker, no catalogue.
    private func applyTypedModelUse(provider: String, model: String) async {
        appendSystem("switching brain → \(provider) · \(model)…")
        let result = await agent.command("configure_model", args: [
            "provider": SlashRouting.configureProvider(provider),
            "model": model,
        ])
        if result.ok {
            await agent.refreshIdentity()
            appendSystem("✓ Brain is now \(provider) · \(model)")
        } else {
            appendSystem("⚠ \(result.error ?? "couldn't switch model")")
        }
    }

    /// Runs ONE turn over the bridge.
    private func runTurn(_ trimmed: String, appendUserBubble: Bool,
                         displayText: String? = nil, images: [String] = [],
                         useTools: Bool? = nil) async -> Bool {
        let selected = sessionKey
        let generation = selectionGeneration
        let toolsEnabled = useTools ?? agenticTools
        let ownsNativeTurn = selected != "dispatcher" || !images.isEmpty || !toolsEnabled
        if ownsNativeTurn {
            guard localTurnSession == nil else { return false }
            localTurnSession = selected
            isSending = true
            recoveryTask?.cancel()
            conversationActivity = []
        }
        defer {
            if ownsNativeTurn {
                localTurnSession = nil
                if selected == sessionKey {
                    isSending = false
                    answerID = nil
                    TranscriptFeed.closeStreaming(in: &messages)
                    startRecovery(session: selected, generation: selectionGeneration)
                } else if pendingSends.contains(where: { $0.sessionID == sessionKey }) {
                    queuePausedByStop = true // switching never implicitly starts retained work
                }
            }
        }
        if !displayConfigLoaded { await loadDisplayConfig() }
        guard selected == sessionKey, generation == selectionGeneration else { return false }
        if sessionKey == "dispatcher" && images.isEmpty && toolsEnabled {
            // A failed/cancelled/uncertain Dispatcher turn was still handled
            // by that authority. Never route the same prompt to native chat.
            return await sendDispatcher(trimmed)
        }

        let turnStarted = Date()
        if appendUserBubble {
            messages.append(ChatMessage(
                author: .user,
                timestamp: turnStarted,
                text: displayText ?? trimmed
            ))
        }

        let placeholder = ChatMessage(
            author: .assistant,
            timestamp: Date(),
            text: "",
            isStreaming: true
        )
        messages.append(placeholder)
        answerID = placeholder.id

        do {
            let reply = try await agent.sendChat(text: trimmed,
                                                 session: selected,
                                                 agenticTools: toolsEnabled,
                                                 imageDataURIs: images,
                                                 speakReplies: TTSManager.shared.autoSpeakEnabled)
            guard selected == sessionKey, generation == selectionGeneration else { return reply.error == nil }
            let replyText = reply.text

            if let i = messages.firstIndex(where: { $0.id == placeholder.id }) {
                messages[i].text = Self.settledReplyText(partial: messages[i].text, reply: replyText,
                                                        interrupted: queuePausedByStop || reply.error != nil)
                messages[i].isStreaming = false
                if queuePausedByStop { messages[i].meta = turnControlLabel }
                if !queuePausedByStop, let s = reply.elapsedS {
                    messages[i].meta = "replied in " + Self.fmtSeconds(s)
                }
                // Prefer turn payload identity; else Gateway active agent.
                var dn = reply.displayName
                var role = reply.agentRole
                if dn == nil || (dn?.isEmpty ?? true) {
                    if let active = try? await GatewayClient.fromEnvironment().listAgents().active {
                        dn = active.displayName
                        role = active.resolvedRole
                    }
                }
                guard selected == sessionKey, generation == selectionGeneration else { return reply.error == nil }
                if let dn, !dn.isEmpty, let i = messages.firstIndex(where: { $0.id == placeholder.id }) {
                    messages[i].displayName = dn
                    messages[i].agentRole = role
                }
            }
            guard selected == sessionKey, generation == selectionGeneration else { return reply.error == nil }
            if let used = reply.ctxUsed, let mx = reply.ctxMax {
                contextUsage = (used, mx)
            }

            // Voice-loop completion: speak the reply through TTS so
            // the operator hears it.  Respects the operator's auto-
            // speak preference; the markdown strip happens inside
            // TTSManager so the synthesizer doesn't read literal
            // asterisks.  Skipped for empty replies.
            NSLog("[ChatViewModel] reply received — autoSpeak=\(TTSManager.shared.autoSpeakEnabled) replyLen=\(replyText.count)")
            if !queuePausedByStop, reply.error == nil, TTSManager.shared.autoSpeakEnabled, !replyText.isEmpty {
                NSLog("[ChatViewModel] dispatching to TTSManager.speak")
                TTSManager.shared.speak(replyText)
            } else {
                NSLog("[ChatViewModel] TTS skipped — autoSpeak=\(TTSManager.shared.autoSpeakEnabled) empty=\(replyText.isEmpty)")
            }
            return reply.error == nil
        } catch {
            guard selected == sessionKey, generation == selectionGeneration else { return false }
            if let i = messages.firstIndex(where: { $0.id == placeholder.id }) {
                messages[i].text = Self.settledReplyText(partial: messages[i].text,
                    reply: "⚠ agent error: \(error.localizedDescription)", interrupted: true)
                messages[i].meta = error.localizedDescription
                messages[i].isStreaming = false
            }
            return false
        }
    }

    nonisolated static func settledReplyText(partial: String, reply: String, interrupted: Bool) -> String {
        interrupted && !partial.isEmpty ? partial : reply
    }

    // MARK: - New Chat / History

    /// Start a separate native chat without evicting the Dispatcher or any
    /// previously loaded conversation. History remains available for return.
    func newChat() async {
        conversationActivity = []
        recoveredApprovalState.clear()
        conversationError = nil
        selectionGeneration = UUID()
        recoveryTask?.cancel()
        recoveryNotice = nil
        isSending = false
        answerID = nil
        isSwitchingSession = true
        let generation = selectionGeneration
        defer { if generation == selectionGeneration { isSwitchingSession = false } }
        let selected = Self.mintSessionKey()
        sessionKey = selected
        controlledRequest = nil
        stopNotice = nil
        controlReadAvailable = false
        dispatcherApproval = nil
        messages.removeAll()
        contextUsage = nil
        do {
            try await recoveryGateway.createConversation(id: selected)
            guard generation == selectionGeneration, sessionKey == selected else { return }
            controlReadAvailable = true
            controlledSessionStatus = "idle"
            startRecovery(session: selected, generation: generation)
        } catch {
            guard generation == selectionGeneration, sessionKey == selected else { return }
            recoveryNotice = "New conversation could not be confirmed. Refresh before resuming queued work. " + error.localizedDescription
        }
    }

    /// The History list's rows — recent conversations, most-active first.
    func fetchSessions() async -> [SessionSummary] {
        let result = await agent.query("list_sessions", args: ["limit": 50])
        guard result.ok, let json = result.json,
              let rows = try? JSONDecoder().decode([SessionSummary].self, from: json)
        else { return [] }
        return rows
    }

    /// Operator picked a conversation out of History: rebuild the local
    /// transcript from its durable turns and adopt its id, so follow-up
    /// turns continue THIS conversation (the core replays the same turns
    /// into the live agent server-side — see
    /// ``main.resume_session_from_store``). Returns false (transcript
    /// untouched) on a bridge failure.
    @discardableResult
    func loadSession(_ id: String) async -> Bool {
        conversationError = nil
        let generation = UUID()
        selectionGeneration = generation
        recoveryTask?.cancel()
        isSwitchingSession = true
        defer { if generation == selectionGeneration { isSwitchingSession = false } }
        if id == "dispatcher" {
            conversationActivity = []
            sessionKey = id
            recoveredApprovalState.clear()
            isSending = false
            answerID = nil
            recoveryNotice = nil
            await refreshDispatcher()
            return generation == selectionGeneration
        }
        do {
            let snapshot = try await recoveryGateway.conversationSnapshot(id: id)
            guard generation == selectionGeneration, snapshot.session_id == id else { return false }
            sessionKey = id
            isSending = localTurnSession == id
            answerID = nil
            applyRecovery(snapshot)
            startRecovery(session: id, generation: generation)
            return true
        } catch {
            guard generation == selectionGeneration else { return false }
            if (error as? GatewayClient.Failure)?.statusCode == 404 {
                // Older local-only history remains viewable; never execute a resume as fallback.
                let result = await agent.query("load_session", args: ["id": id, "resume": false])
                guard generation == selectionGeneration else { return false }
                if result.ok, let json = result.json,
                   let turns = try? JSONDecoder().decode([SessionTurn].self, from: json), !turns.isEmpty {
                    sessionKey = id
                    recoveredApprovalState.clear()
                    isSending = localTurnSession == id
                    answerID = nil
                    controlledRequest = nil
                    controlReadAvailable = false
                    controlledSessionStatus = nil
                    stopNotice = nil
                    messages = Self.rebuildMessages(from: turns)
                    recoveryNotice = "Saved local history — no Gateway live request is available for this conversation."
                    return true
                }
            }
            conversationError = "Conversation could not be recovered. " + error.localizedDescription
            startRecovery(session: sessionKey, generation: generation)
            return false // retain the currently visible transcript
        }
    }

    private func applyRecovery(_ snapshot: GatewayClient.ConversationSnapshot) {
        conversationActivity = snapshot.activity_context ?? []
        if let request = snapshot.latest_request, stopRequestedIDs.contains(request.request_id) {
            recoveredApprovalState.clear()
        } else {
            recoveredApprovalState.bind(session: snapshot.session_id, request: snapshot.latest_request,
                                        profile: snapshot.profile, context: snapshot.activity_context ?? [])
        }
        var existing = messages
        messages = snapshot.messages.map { row in
            let author: ChatMessage.Author = row.role == "user" ? .user : (row.role == "assistant" ? .assistant : .system)
            // Preserve already rendered activity/identity when canonical text agrees.
            if let index = existing.firstIndex(where: { $0.author == author && $0.text == row.content }) {
                var preserved = existing.remove(at: index)
                preserved.isStreaming = false
                return preserved
            }
            return ChatMessage(author: author, timestamp: Date(timeIntervalSince1970: row.timestamp), text: row.content)
        }
        controlledRequest = snapshot.latest_request
        controlledSessionStatus = snapshot.status
        controlReadAvailable = true
        if let request = snapshot.latest_request,
           ["cancelling", "cancelled", "execution_unknown"].contains(request.status) {
            if !resumedAfterStopIDs.contains(request.request_id) { queuePausedByStop = true }
            stopNotice = request.stopLabel
        } else if let request = snapshot.latest_request, request.isActive, stopRequestedIDs.contains(request.request_id) {
            stopNotice = "Stop unconfirmed — waiting for backend observation; cancellation will not be resent"
        } else { stopNotice = snapshot.latest_request?.status == "failed" ? snapshot.latest_request?.stopLabel : nil }
        answerID = nil
        if !snapshot.partial_text.isEmpty || snapshot.latest_request?.isActive == true {
            let answer = ChatMessage(author: .assistant, timestamp: .now, text: snapshot.partial_text,
                                     isStreaming: snapshot.latest_request?.isActive == true)
            messages.append(answer)
            answerID = answer.id
        }
        for pending in pendingSends where pending.sessionID == sessionKey {
            messages.append(ChatMessage(author: .user, timestamp: .now, text: pending.display))
        }
        contextUsage = nil
        recoveryNotice = nil
    }

    private func startRecovery(session: String, generation: UUID) {
        recoveryTask?.cancel()
        guard session != "dispatcher", localTurnSession != session else { return }
        let gateway = recoveryGateway
        recoveryTask = Task { [weak self] in
            while !Task.isCancelled {
                do {
                    let snapshot = try await gateway.conversationSnapshot(id: session)
                    guard !Task.isCancelled, self?.selectionGeneration == generation,
                          self?.sessionKey == session, self?.localTurnSession != session else { return }
                    self?.applyRecovery(snapshot)
                    var cursor = snapshot.event_cursor
                    for try await event in gateway.streamEvents(sessionID: session, lastEventID: cursor) {
                        guard !Task.isCancelled, self?.selectionGeneration == generation,
                              self?.sessionKey == session, self?.localTurnSession != session else { return }
                        guard event.eventID > cursor else { continue }
                        cursor = event.eventID
                        if event.event == "approval.resolved" || event.event == "approval.request" {
                            await self?.recoveredApprovalState.refresh()
                        }
                        guard event.sessionID == session else { continue }
                        if event.event.hasPrefix("tool.") || event.event == "agent.handoff" || event.event.hasPrefix("agent.handoff.") {
                            if let object = try? JSONSerialization.jsonObject(with: event.data) as? [String: Any],
                               object["request_id"] as? String == self?.controlledRequest?.request_id,
                               let data = try? JSONSerialization.data(withJSONObject: ((object["handoff"] as? [String: Any]) ?? object).merging(["event": event.event]) { _, new in new }),
                               let activity = try? JSONDecoder().decode(GatewayClient.ConversationSnapshot.Activity.self, from: data) {
                                self?.conversationActivity.append(activity)
                                if let count = self?.conversationActivity.count, count > 50 {
                                    self?.conversationActivity.removeFirst(count - 50)
                                }
                            }
                        }
                        if event.event == "turn.start" || event.isTerminal {
                            if ["turn.cancelled", "turn.unknown"].contains(event.event) { self?.queuePausedByStop = true }
                            let refreshed = try await gateway.conversationSnapshot(id: session)
                            guard !Task.isCancelled, self?.selectionGeneration == generation,
                                  self?.sessionKey == session, self?.localTurnSession != session else { return }
                            self?.applyRecovery(refreshed)
                            cursor = max(cursor, refreshed.event_cursor)
                        } else if event.event == "turn.delta",
                                  let object = try? JSONSerialization.jsonObject(with: event.data) as? [String: Any],
                                  object["request_id"] as? String == self?.controlledRequest?.request_id,
                                  let delta = object["delta"] as? String,
                                  let model = self {
                            TranscriptFeed.appendAnswerDelta(delta, to: &model.messages, answerID: model.answerID)
                        }
                    }
                    self?.recoveryNotice = "Live connection closed — reconnecting; work was not resubmitted."
                } catch {
                    guard !Task.isCancelled, self?.selectionGeneration == generation else { return }
                    self?.recoveryNotice = "Live connection unavailable — reconnecting; work was not resubmitted. " + error.localizedDescription
                }
                do { try await Task.sleep(for: .seconds(2)) } catch { return }
            }
        }
    }

    /// Pure turn-list -> transcript mapping, split out so it's testable
    /// without a live ``AgentBridge`` (see ChatViewModelTests).
    nonisolated static func rebuildMessages(from turns: [SessionTurn]) -> [ChatMessage] {
        turns.map { turn in
            ChatMessage(author: turn.role == "user" ? .user : .assistant,
                       timestamp: Date(timeIntervalSince1970: turn.ts),
                       text: turn.text)
        }
    }

    // MARK: - Formatting

    /// "3.2s" under ten seconds, "42s" above — the TUI's compact style.
    static func fmtSeconds(_ s: Double) -> String {
        s < 10 ? String(format: "%.1fs", s) : "\(Int(s.rounded()))s"
    }

    /// "18.3K" / "1M" / "512" — TUI ``_kfmt`` style. The old
    /// ``n/1000 → %.1fK`` path printed a 1,048,576-token window as
    /// ``1048.6K`` instead of ``1M``.
    nonisolated static func fmtTokens(_ n: Int) -> String {
        let absValue = abs(n)
        if absValue == 1_048_576 { return n < 0 ? "-1M" : "1M" }
        if absValue < 1_000 { return "\(n)" }
        let sign = n < 0 ? "-" : ""
        let threshold: Double
        let suffix: String
        if absValue >= 1_000_000_000 {
            threshold = 1_000_000_000
            suffix = "B"
        } else if absValue >= 1_000_000 {
            threshold = 1_000_000
            suffix = "M"
        } else {
            threshold = 1_000
            suffix = "K"
        }
        let scaled = Double(absValue) / threshold
        let text: String
        if scaled < 10 {
            text = String(format: "%.2f", scaled)
        } else if scaled < 100 {
            text = String(format: "%.1f", scaled)
        } else {
            text = String(format: "%.0f", scaled)
        }
        var trimmed = text
        while trimmed.contains(".") && (trimmed.hasSuffix("0") || trimmed.hasSuffix(".")) {
            trimmed = String(trimmed.dropLast())
        }
        return "\(sign)\(trimmed)\(suffix)"
    }
}
