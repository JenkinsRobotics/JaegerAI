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
    var thoughtText: String
    var toolItems: [ToolCallItem]

    init(
        id: UUID = UUID(),
        author: Author,
        timestamp: Date = Date(),
        text: String = "",
        isStreaming: Bool = false,
        meta: String? = nil,
        thoughtText: String = "",
        toolItems: [ToolCallItem] = []
    ) {
        self.id = id
        self.author = author
        self.timestamp = timestamp
        self.text = text
        self.isStreaming = isStreaming
        self.meta = meta
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
    @Published private(set) var pendingSends: [String] = []

    /// Composer text — bound to the chat window's TextField.  Owned
    /// by the view-model so transcription results (from STT) can
    /// drop straight into it without needing a callback up to the
    /// view.  The view does ``$chat.composerText`` for the binding.
    @Published var composerText: String = ""

    /// True while a STT pass is running.  Disables the send button,
    /// shows a "transcribing…" indicator in the status bar.
    @Published private(set) var isTranscribing: Bool = false

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

    init(agent: AgentBridge, sessionKey: String = ChatViewModel.mintSessionKey()) {
        self.agent = agent
        self.sessionKey = sessionKey
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
        do {
            try voice.startRecording()
        } catch {
            appendSystem("voice unavailable — \(error.localizedDescription)")
        }
    }

    /// Stop push-to-talk capture and hand the buffer to the STT
    /// manager.  Transcription lands in ``composerText`` so the
    /// operator can review / edit before sending — same flow Apple
    /// Notes uses for voice dictation, lower stakes than auto-
    /// submitting to the agent.  A system bubble notes capture
    /// duration + which backend ran for telemetry.
    func stopVoice() {
        voice.stopRecording()
        guard let captured = voice.takeCapturedAudio() else { return }
        let seconds = Double(captured.samples.count) / captured.format.sampleRate
        let backendName = STTManager.shared.activeBackend.displayName

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
        STTManager.shared.transcribe(
            samples: captured.samples,
            format: captured.format
        ) { [weak self] result in
            // STTManager / backends guarantee the completion runs on
            // the main queue.  ``MainActor.assumeIsolated`` is the
            // ergonomic way to tell the compiler that without forcing
            // a Task hop — the runtime asserts in debug builds if the
            // guarantee is wrong.
            MainActor.assumeIsolated {
                guard let self else { return }
                self.isTranscribing = false
                switch result {
                case .success(let r):
                    // Append to the composer rather than replacing —
                    // if the operator was already mid-typing, we don't
                    // clobber their work.  A space joins the two
                    // pieces cleanly.
                    if self.composerText.isEmpty {
                        self.composerText = r.text
                    } else {
                        self.composerText += " " + r.text
                    }
                    self.appendSystem(String(
                        format: "✓ transcribed in %.1fs · review and hit send",
                        r.elapsedSeconds
                    ))
                case .failure(let err):
                    self.appendSystem(
                        "⚠ transcription failed — \(err.localizedDescription)"
                    )
                }
            }
        }
    }

    deinit {
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
        switch event.name {
        case "subscribed":
            // The "we're listening now" handshake.  Don't display.
            return
        case "turn.start":
            return
        case "turn.end":
            // Close any active streaming thought/tool groups
            for i in messages.indices {
                if messages[i].author == .thought || messages[i].author == .toolGroup {
                    messages[i].isStreaming = false
                }
            }
            return
        case "thought.start", "deep_think.start", "thinking", "thought.delta", "thought":
            guard activityTrace != "off" else { return }
            let text = event.payload["text"]?.get(String.self)
                ?? event.payload["thought"]?.get(String.self)
                ?? event.payload["delta"]?.get(String.self)
                ?? ""
            if let i = messages.lastIndex(where: { $0.author == .thought && $0.isStreaming }) {
                if !text.isEmpty && !messages[i].thoughtText.contains(text) {
                    messages[i].thoughtText += (messages[i].thoughtText.isEmpty ? "" : "\n\n") + text
                }
            } else {
                messages.append(ChatMessage(
                    author: .thought,
                    timestamp: Date(),
                    isStreaming: true,
                    thoughtText: text
                ))
            }
        case "thought.end", "deep_think.end":
            if let i = messages.lastIndex(where: { $0.author == .thought && $0.isStreaming }) {
                messages[i].isStreaming = false
            }
        case "tool.call", "tool.start":
            guard activityTrace != "off" else { return }
            let name = event.payload["tool"]?.get(String.self)
                ?? event.payload["name"]?.get(String.self)
                ?? "tool"
            if name == "work_ledger" { return }
            let detail = event.payload["detail"]?.get(String.self) ?? ""
            let item = ToolCallItem(name: name, detail: detail, isStreaming: true)

            let lastUserIdx = messages.lastIndex(where: { $0.author == .user }) ?? -1
            if let i = messages.lastIndex(where: { $0.author == .toolGroup }), i > lastUserIdx {
                messages[i].toolItems.append(item)
                messages[i].isStreaming = true
            } else {
                messages.append(ChatMessage(
                    author: .toolGroup,
                    timestamp: Date(),
                    isStreaming: true,
                    toolItems: [item]
                ))
            }
        case "tool.result", "tool.end", "tool.complete":
            if let i = messages.lastIndex(where: { $0.author == .toolGroup }) {
                let ok = event.payload["ok"]?.get(Bool.self) ?? true
                let elapsed = event.payload["elapsed_s"]?.get(Double.self) ?? 0
                if let itemIdx = messages[i].toolItems.lastIndex(where: { $0.isStreaming }) {
                    messages[i].toolItems[itemIdx].ok = ok
                    messages[i].toolItems[itemIdx].elapsed_s = elapsed
                    messages[i].toolItems[itemIdx].isStreaming = false
                }
                if !messages[i].toolItems.contains(where: { $0.isStreaming }) {
                    messages[i].isStreaming = false
                }
            }
        case "task.progress":
            // Owned by ``AgentBridge.taskProgress`` (the chat drawer and
            // the ⌥Space HUD). Don't turn ledger ticks into tool chips.
            return
        case "token", "message.delta":
            let delta = event.payload["text"]?.get(String.self)
                ?? event.payload["delta"]?.get(String.self)
                ?? ""
            guard !delta.isEmpty else { return }
            if let i = messages.lastIndex(where: { $0.author == .assistant }) {
                messages[i].text += delta
            }
        default:
            return
        }
    }

    /// Send a user turn through the agent's ``chat.send`` verb.
    func send(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

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
            agent.cancelTurn()
            appendSystem("stop requested")
            return
        case .steer(let guidance):
            agent.steer(guidance)
            appendSystem("steered: \(guidance)")
            return
        case .local(let notice):
            appendSystem(notice)
            return
        case .chat(let prompt, let display):
            await enqueueOrRun(prompt, display: display)
        case .passThrough:
            await enqueueOrRun(trimmed, display: trimmed)
        }
    }

    /// Queue behind an in-flight turn, or run immediately.
    private func enqueueOrRun(_ prompt: String, display: String) async {
        if isSending {
            pendingSends.append(prompt)
            messages.append(ChatMessage(
                author: .user, timestamp: Date(), text: display))
            return
        }
        _ = await runTurn(prompt, appendUserBubble: true, displayText: display)
        while !pendingSends.isEmpty {
            let next = pendingSends.removeFirst()
            _ = await runTurn(next, appendUserBubble: false)
        }
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
                         displayText: String? = nil) async -> Bool {
        if !displayConfigLoaded { await loadDisplayConfig() }

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

        isSending = true
        defer {
            isSending = false
            // Close any remaining streaming states
            for i in messages.indices {
                if messages[i].isStreaming {
                    messages[i].isStreaming = false
                }
            }
        }

        do {
            let reply = try await agent.sendChat(text: trimmed,
                                                 session: sessionKey)
            let replyText = reply.text

            if let i = messages.firstIndex(where: { $0.id == placeholder.id }) {
                messages[i].text = replyText
                messages[i].isStreaming = false
                if let s = reply.elapsedS {
                    messages[i].meta = "replied in " + Self.fmtSeconds(s)
                }
            }
            if let used = reply.ctxUsed, let mx = reply.ctxMax {
                contextUsage = (used, mx)
            }

            // Voice-loop completion: speak the reply through TTS so
            // the operator hears it.  Respects the operator's auto-
            // speak preference; the markdown strip happens inside
            // TTSManager so the synthesizer doesn't read literal
            // asterisks.  Skipped for empty replies.
            NSLog("[ChatViewModel] reply received — autoSpeak=\(TTSManager.shared.autoSpeakEnabled) replyLen=\(replyText.count)")
            if TTSManager.shared.autoSpeakEnabled, !replyText.isEmpty {
                NSLog("[ChatViewModel] dispatching to TTSManager.speak")
                TTSManager.shared.speak(replyText)
            } else {
                NSLog("[ChatViewModel] TTS skipped — autoSpeak=\(TTSManager.shared.autoSpeakEnabled) empty=\(replyText.isEmpty)")
            }
            return true
        } catch {
            if let i = messages.firstIndex(where: { $0.id == placeholder.id }) {
                messages[i].text =
                    "⚠ agent error: \(error.localizedDescription)"
                messages[i].isStreaming = false
            }
            return false
        }
    }

    // MARK: - New Chat / History

    /// "New Chat": mint a fresh session id, evict the old one on the
    /// Python side (best-effort — a failed command just means the old
    /// key's in-memory state lingers, harmless), and reset the local
    /// transcript. Always leaves the view model on a NEW key, even if
    /// the bridge call fails — the operator's "new chat" intent must not
    /// silently no-op just because the pipe hiccuped.
    func newChat() async {
        isSwitchingSession = true
        defer { isSwitchingSession = false }
        let result = await agent.command("new_session", args: ["old_id": sessionKey])
        var newKey = Self.mintSessionKey()
        if result.ok, let data = result.json,
           let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
           let id = obj["id"] as? String, !id.isEmpty {
            newKey = id
        }
        sessionKey = newKey
        messages.removeAll()
        contextUsage = nil
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
        guard id != sessionKey else { return true }   // already viewing it
        isSwitchingSession = true
        defer { isSwitchingSession = false }
        let result = await agent.query("load_session", args: ["id": id])
        guard result.ok, let json = result.json,
              let turns = try? JSONDecoder().decode([SessionTurn].self, from: json)
        else { return false }
        sessionKey = id
        messages = Self.rebuildMessages(from: turns)
        contextUsage = nil
        return true
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
