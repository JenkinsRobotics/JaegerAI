//
//  AmbientLoop.swift
//  JaegerAI / Voice
//
//  The OS 1 ambient loop: gateway event stream in, speech out, and an
//  interrupt path fast enough that talking over the agent stops it.
//
//      GatewayClient.streamEvents ──► ClauseBuffer ──► TTSManager
//                                                        │
//      VoiceRecorder tap ──► SpeechEnergyDetector ────────┘  barge-in
//
//  Two decisions carry the latency budget:
//
//  * **Speak on clauses, not turns.** Waiting for ``turn.finish`` before
//    speaking makes the agent mute for the whole generation. The buffer
//    flushes on sentence and clause punctuation, so speech starts on the
//    first few words while the rest is still arriving.
//
//  * **Cancel locally first.** On speech onset we stop TTS and drop queued
//    text immediately, then tell the gateway. Awaiting the network before
//    going quiet would put a round trip inside the interrupt path and blow
//    the 100 ms budget.
//

import Foundation

/// Splits a token stream into speakable clauses.
///
/// Boundaries are `.` `!` `?` `\n` (sentence) and `,` `;` `:` (clause,
/// only once enough text has accumulated to be worth speaking). The
/// minimum length stops "Dr." or a bare "1." from being flushed as a
/// one-word utterance, which sounds like stuttering.
struct ClauseBuffer {
    private(set) var pending: String = ""

    /// Don't flush a clause shorter than this; sentence enders ignore it.
    ///
    /// 16 is the balance point: it still blocks stutter-fragments like
    /// "Well," (5) and "Dr." but passes ordinary opening clauses such as
    /// "I checked the logs," (19). Set higher and the agent stays silent
    /// through the first clause of most replies, which is exactly the
    /// latency this buffer exists to remove.
    var minimumClauseLength: Int = 16

    private static let sentenceEnders: Set<Character> = [".", "!", "?", "\n"]
    private static let clauseEnders: Set<Character> = [",", ";", ":"]

    /// Append streamed text; returns any complete clauses ready to speak.
    mutating func append(_ chunk: String) -> [String] {
        pending += chunk
        var ready: [String] = []

        while let index = Self.boundary(in: pending, minimum: minimumClauseLength) {
            let piece = String(pending[...index]).trimmingCharacters(in: .whitespacesAndNewlines)
            pending = String(pending[pending.index(after: index)...])
            if !piece.isEmpty { ready.append(piece) }
        }
        return ready
    }

    /// Everything still buffered — call at ``turn.finish`` so a reply that
    /// ends without punctuation is still spoken.
    mutating func flush() -> String? {
        let remainder = pending.trimmingCharacters(in: .whitespacesAndNewlines)
        pending = ""
        return remainder.isEmpty ? nil : remainder
    }

    mutating func reset() { pending = "" }

    private static func boundary(in text: String, minimum: Int) -> String.Index? {
        var offset = 0
        for index in text.indices {
            offset += 1
            let character = text[index]
            if sentenceEnders.contains(character) { return index }
            if clauseEnders.contains(character), offset >= minimum { return index }
        }
        return nil
    }
}

/// What the menu bar shows. One enum so the icon can never disagree with
/// what the audio layer is doing.
enum AmbientState: String, Sendable, Equatable {
    case idle
    case listening
    case thinking
    case speaking
    case interrupted
}

@MainActor
final class AmbientLoop: ObservableObject {

    @Published private(set) var state: AmbientState = .idle
    @Published private(set) var lastError: String?
    @Published private(set) var transcriptTail: String = ""

    private let gateway: GatewayClient
    private let tts: TTSManager
    private let detector: SpeechEnergyDetector

    private var sessionID: String?
    private var streamTask: Task<Void, Never>?
    private var buffer = ClauseBuffer()
    private var lastEventID = 0

    /// Guards against a cancel racing the next turn: every turn gets an
    /// epoch, and events from a superseded epoch are dropped rather than
    /// spoken over the new one.
    private var activeRequestID: String?
    private var acceptedRequestID: String?
    private var stopOnAcceptance: Set<String> = []
    private var epoch = 0

    /// Speak-first: proactive feed watcher, its cursor, and event ids
    /// already voiced (the SSE path and the feed can both carry one event).
    private var feedTask: Task<Void, Never>?
    private var feedCursor: Int?
    private var spokenProactiveIDs: Set<Int> = []

    init(gateway: GatewayClient, tts: TTSManager, detector: SpeechEnergyDetector) {
        self.gateway = gateway
        self.tts = tts
        self.detector = detector
    }

    /// Connect a recorder's live tap so speech can interrupt playback.
    ///
    /// Without this the detector runs and nothing listens: `handleSpeechOnset`
    /// existed, was tested, and was never called by anything — the agent
    /// could be talked over with no effect. Opening the mic in monitor mode
    /// is what makes barge-in possible at all, because push-to-talk cannot
    /// help: the operator is not holding a key at the moment they decide to
    /// interrupt.
    /// The live tap, set by ``AmbientCoordinator``. Weak: the coordinator
    /// owns the recorder's lifetime, and a strong reference here would keep
    /// a microphone alive past the coordinator that is supposed to govern it.
    weak var recorder: VoiceRecorder?

    /// Convenience wiring for tests and any caller managing its own
    /// recorder. Production goes through ``AmbientCoordinator.activate()``,
    /// which also owns the open/close policy.
    func attach(recorder: VoiceRecorder) throws {
        self.recorder = recorder
        recorder.onSpeechOnset = { [weak self] in self?.handleSpeechOnset() }
        recorder.onSpeechEnded = { [weak self] in self?.handleSpeechEnded() }
        try recorder.startMonitoring()
    }

    func detach(recorder: VoiceRecorder) {
        if self.recorder === recorder { self.recorder = nil }
        recorder.onSpeechOnset = nil
        recorder.onSpeechEnded = nil
        recorder.stopMonitoring()
    }

    // MARK: - Session

    func attach(sessionID: String) {
        self.sessionID = sessionID
        lastEventID = 0
        state = .idle
    }

    // MARK: - Speaking a turn

    /// Send text and speak the reply as it streams.
    func send(_ text: String) async {
        guard let sessionID else {
            lastError = "No session attached"
            return
        }
        epoch += 1
        let thisEpoch = epoch

        buffer.reset()
        state = .thinking
        lastError = nil

        do {
            let requestID = UUID().uuidString
            activeRequestID = requestID
            acceptedRequestID = nil
            let accepted = try await gateway.sendTurn(sessionID: sessionID, text: text, requestID: requestID)
            activeRequestID = accepted.request_id
            acceptedRequestID = accepted.request_id
            if stopOnAcceptance.remove(requestID) != nil {
                // Stop raced admission. The original cancel was deferred,
                // so this is the one cancellation, never an uncertain resend.
                let receipt = try await gateway.cancelTurn(sessionID: sessionID, requestID: accepted.request_id)
                lastError = receipt.stopLabel
                return
            }
        } catch {
            // 409 = a turn is already running. Surface it; retrying blindly
            // would stack turns the operator never asked for.
            lastError = "Send failed: \(error.localizedDescription)"
            state = .idle
            return
        }
        startStream(sessionID: sessionID, epoch: thisEpoch)
    }

    private func startStream(sessionID: String, epoch thisEpoch: Int) {
        streamTask?.cancel()
        streamTask = Task { [weak self] in
            guard let self else { return }
            do {
                for try await event in gateway.streamEvents(
                    sessionID: sessionID, lastEventID: lastEventID,
                ) {
                    if Task.isCancelled { return }
                    await self.consume(event, epoch: thisEpoch)
                }
            } catch {
                await MainActor.run {
                    guard thisEpoch == self.epoch else { return }
                    // Never fail quiet: a dropped stream must be visible,
                    // otherwise the agent just appears to stop thinking.
                    self.lastError = "Stream error: \(error.localizedDescription)"
                    self.state = .idle
                }
            }
        }
    }

    private func consume(_ event: GatewayClient.StreamEvent, epoch thisEpoch: Int) async {
        guard thisEpoch == epoch else { return }   // superseded by a newer turn
        if event.eventID > lastEventID { lastEventID = event.eventID }

        switch event.event {
        case "turn.start":
            state = .thinking

        case "turn.delta":
            guard let text = event.deltaText, !text.isEmpty else { return }
            transcriptTail = String((transcriptTail + text).suffix(400))
            for clause in buffer.append(text) {
                speak(clause)
            }

        case "turn.finish":
            if let tail = buffer.flush() { speak(tail) }
            state = tts.isSpeaking ? .speaking : .idle

        case "turn.failed":
            lastError = "Turn failed"
            state = .idle

        case "turn.cancelled":
            lastError = "Cancelled — backend turn settled"
            state = .idle

        case "turn.unknown":
            lastError = "Outcome unknown — external work may still be running"
            state = .interrupted

        case "notification.proactive":
            guard let notification = event.proactiveNotification else { return }
            deliverProactive(eventID: event.eventID, body: notification.body,
                             speak: notification.speak)

        default:
            break
        }
    }

    // MARK: - Speak first

    /// Start watching jaegerd's proactive feed. Idempotent. The first poll
    /// only sets the cursor, so launching the app never replays history.
    func startProactiveWatch(intervalNanoseconds: UInt64 = 4_000_000_000) {
        guard feedTask == nil else { return }
        feedTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.pollProactiveFeed()
                try? await Task.sleep(nanoseconds: intervalNanoseconds)
            }
        }
    }

    func stopProactiveWatch() {
        feedTask?.cancel()
        feedTask = nil
    }

    func pollProactiveFeed() async {
        let since = feedCursor ?? 0
        guard let feed = try? await gateway.listNotifications(since: since) else {
            return   // gateway down or Stop: stay quiet, try next tick
        }
        guard feedCursor != nil else {
            feedCursor = feed.cursor
            return
        }
        feedCursor = max(since, feed.cursor)
        for item in feed.notifications {
            deliverProactive(eventID: item.eventID, body: item.body ?? "",
                             speak: item.speak ?? true)
        }
    }

    /// Show and (optionally) say one proactive message, once per event.
    /// Never talks over a live turn: while thinking or speaking the text
    /// goes to the transcript only.
    func deliverProactive(eventID: Int, body: String, speak shouldSpeak: Bool) {
        let text = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !spokenProactiveIDs.contains(eventID) else { return }
        spokenProactiveIDs.insert(eventID)
        if spokenProactiveIDs.count > 256 { spokenProactiveIDs.removeAll() ; spokenProactiveIDs.insert(eventID) }
        transcriptTail = String((transcriptTail + text).suffix(400))
        lastProactive = text
        if shouldSpeak && state != .thinking && state != .speaking {
            speak(text)
        }
    }

    @Published private(set) var lastProactive: String?

    private func speak(_ clause: String) {
        state = .speaking
        // Suppress the mic for the duration plus a reverb tail, so the
        // agent's own output cannot trip its barge-in detector.
        detector.setOutputActive(true)
        tts.speak(clause)
    }

    // MARK: - Barge-in

    /// Called from the audio tap on speech onset. Must stay cheap.
    ///
    /// Order matters: local stop first so the room goes quiet immediately,
    /// network cancel after. Awaiting the gateway before stopping would put
    /// a round trip inside the interrupt and miss the 100 ms budget.
    func handleSpeechOnset() {
        guard state == .speaking || state == .thinking else {
            if state == .idle { state = .listening }
            return
        }

        tts.stop()                      // cancels utterance + queued buffers
        buffer.reset()                  // drop text not yet spoken
        detector.setOutputActive(false)
        state = .interrupted
        epoch += 1                      // orphan in-flight stream events

        streamTask?.cancel()
        streamTask = nil

        if let requestID = activeRequestID, acceptedRequestID != requestID {
            stopOnAcceptance.insert(requestID)
            lastError = "Stop will be requested when submission acceptance is known"
        } else if let sessionID, let requestID = activeRequestID {
            Task { [gateway, weak self] in
                do {
                    let receipt = try await gateway.cancelTurn(sessionID: sessionID, requestID: requestID)
                    self?.lastError = receipt.stopLabel
                } catch {
                    self?.lastError = "Stop unconfirmed: " + error.localizedDescription
                }
            }
        }
        state = .listening
    }

    func handleSpeechEnded() {
        if state == .listening { state = .idle }
    }

    /// TTS finished naturally — reopen the mic after the tail.
    func handleSpeechSynthesisFinished() {
        detector.setOutputActive(false)
        if state == .speaking { state = .idle }
    }

    func stop() {
        streamTask?.cancel()
        streamTask = nil
        tts.stop()
        buffer.reset()
        detector.setOutputActive(false)
        state = .idle
    }
}
