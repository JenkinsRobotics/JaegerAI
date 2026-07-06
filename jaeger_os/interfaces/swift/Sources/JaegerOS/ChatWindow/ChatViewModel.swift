//
//  ChatViewModel.swift
//  JaegerOS / ChatWindow
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

/// One bubble in the transcript.  Carries the minimum the view needs;
/// the timestamp is preserved so a future log/export pass has it.
struct ChatMessage: Identifiable, Equatable {
    /// What kind of bubble this is.  ``.toolCall`` and ``.thinking``
    /// show up as compact inline chips, not full message bubbles —
    /// they exist so the operator can see what the agent is doing
    /// mid-turn (the telemetry the Terminal TUI shows by default).
    enum Author: Equatable {
        case user
        case assistant
        case system     // connection notices, errors, etc.
        case thinking   // "thinking…" trail from the agent loop
        case toolCall   // a tool invocation in flight or just done
    }

    let id = UUID()
    let author: Author
    let timestamp: Date
    var text: String
    /// True while the assistant is still streaming tokens into ``text``.
    /// (Week 2.5 wiring — we keep the field now so the view can fade in
    /// a cursor / spinner when the streaming pass lands.)
    var isStreaming: Bool = false
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

    /// Composer text — bound to the chat window's TextField.  Owned
    /// by the view-model so transcription results (from STT) can
    /// drop straight into it without needing a callback up to the
    /// view.  The view does ``$chat.composerText`` for the binding.
    @Published var composerText: String = ""

    /// True while a STT pass is running.  Disables the send button,
    /// shows a "transcribing…" indicator in the status bar.
    @Published private(set) var isTranscribing: Bool = false

    /// The session key the agent uses to scope rolling history.  We
    /// keep this constant within one chat window's lifetime so the
    /// agent can correlate follow-up turns.
    let sessionKey: String

    private let agent: AgentBridge
    private var eventToken: UUID?

    /// Push-to-talk recorder.  Owned by the view-model so the same
    /// instance survives across composer interactions; the view binds
    /// to its ``@Published`` state for the level meter + recording
    /// indicator.  Week 4 wires the captured audio into a
    /// ``transcribe`` round-trip; Week 5 swaps in CoreML Whisper.
    let voice = VoiceRecorder()

    init(agent: AgentBridge, sessionKey: String = "desktop-app") {
        self.agent = agent
        self.sessionKey = sessionKey
        // Subscribe to agent events so we can show thinking + tool
        // chips inline as the agent works.  Captures a weak self so
        // we don't pin the view model alive past the chat window's
        // lifetime.
        self.eventToken = agent.addEventListener { [weak self] event in
            self?.handle(event: event)
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
            // Each new turn starts.  Already obvious from the user
            // bubble — don't duplicate.
            return
        case "turn.end":
            return
        case "thought.start", "deep_think.start", "thinking":
            // One chip per in-flight turn — the busy `state` frames can
            // re-fire mid-turn (tool hops), and a duplicate chip per hop
            // reads as noise.
            guard !messages.contains(where: { $0.author == .thinking }) else {
                return
            }
            messages.append(ChatMessage(
                author: .thinking,
                timestamp: Date(),
                text: "thinking…",
                isStreaming: true
            ))
        case "thought.end", "deep_think.end":
            // The chip is TRANSIENT — typing-dots semantics. It exists
            // only while the turn is in flight; when the agent stops
            // thinking (reply landed / turn ended) it leaves the
            // transcript entirely instead of lingering as a stale
            // "thinking…" line under every reply.
            messages.removeAll { $0.author == .thinking }
        case "tool.call", "tool.start":
            let name = event.payload["tool"]?.get(String.self)
                ?? event.payload["name"]?.get(String.self)
                ?? "tool"
            messages.append(ChatMessage(
                author: .toolCall,
                timestamp: Date(),
                text: "🔧 \(name)",
                isStreaming: true
            ))
        case "tool.result", "tool.end", "tool.complete":
            // Close out the most recent in-flight tool-call chip
            // with a ✓ or ✗ depending on whether the agent flagged
            // an error in the payload.
            if let i = messages.lastIndex(where: {
                $0.author == .toolCall && $0.isStreaming
            }) {
                let ok = event.payload["ok"]?.get(Bool.self) ?? true
                messages[i].isStreaming = false
                messages[i].text = "\(messages[i].text) \(ok ? "✓" : "✗")"
            }
        case "token", "message.delta":
            // Streaming token — append to the most recent assistant
            // bubble.  Useful once chat.send is split into start +
            // streaming.  For now chat.send is synchronous so this
            // path is dormant.
            let delta = event.payload["text"]?.get(String.self)
                ?? event.payload["delta"]?.get(String.self)
                ?? ""
            guard !delta.isEmpty else { return }
            if let i = messages.lastIndex(where: { $0.author == .assistant }) {
                messages[i].text += delta
            }
        default:
            // Unknown event — keep it out of the UI; NSLog already
            // showed it for diagnostics.
            return
        }
    }

    /// Send a user turn through the agent's ``chat.send`` verb.  The
    /// user bubble appears immediately; the assistant bubble lands
    /// once the agent replies.  Errors become inline system bubbles.
    func send(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        guard !isSending else { return }

        // User bubble lands now so the operator sees their message
        // immediately even if the agent is slow to reply.
        messages.append(ChatMessage(
            author: .user,
            timestamp: Date(),
            text: trimmed
        ))

        // Placeholder assistant bubble — we'll fill in once the
        // response lands.  Marked as streaming so the view can show a
        // cursor / spinner if it wants to.  Tracked BY ID, not index —
        // thinking chips come and go mid-turn (they're transient now),
        // so a captured index could drift.
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
            // Belt-and-braces: no thinking chip survives past its turn.
            messages.removeAll { $0.author == .thinking }
        }

        do {
            // One turn over the bridge → the reply text. The session key
            // keeps THIS window's conversation isolated on the Python side.
            let replyText = try await agent.sendChat(text: trimmed,
                                                     session: sessionKey)
            if let i = messages.firstIndex(where: { $0.id == placeholder.id }) {
                messages[i].text = replyText
                messages[i].isStreaming = false
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
        } catch {
            if let i = messages.firstIndex(where: { $0.id == placeholder.id }) {
                messages[i].text =
                    "⚠ agent error: \(error.localizedDescription)"
                messages[i].isStreaming = false
            }
        }
    }
}
