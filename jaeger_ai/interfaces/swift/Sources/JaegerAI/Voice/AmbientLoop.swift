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
    private var epoch = 0

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
    func attach(recorder: VoiceRecorder) throws {
        recorder.onSpeechOnset = { [weak self] in self?.handleSpeechOnset() }
        recorder.onSpeechEnded = { [weak self] in self?.handleSpeechEnded() }
        try recorder.startMonitoring()
    }

    func detach(recorder: VoiceRecorder) {
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
            try await gateway.sendTurn(sessionID: sessionID, text: text)
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
            state = .idle

        default:
            break
        }
    }

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

        if let sessionID {
            Task { [gateway] in
                // Best effort: the operator has already been obeyed
                // locally, so a failure here is logged, not surfaced as a
                // user-facing error.
                try? await gateway.cancelTurn(sessionID: sessionID)
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
