//
//  SpeechEnergyDetector.swift
//  JaegerAI / Voice
//
//  Local voice-activity detection by short-time energy, used for barge-in:
//  deciding fast enough that the operator can talk over the agent and have
//  it stop mid-word.
//
//  Why energy and not a model: barge-in needs an answer in one audio frame,
//  not after a decode. A 20–30 ms RMS window costs microseconds and runs
//  inside the existing capture tap, so the detection latency is bounded by
//  the buffer size rather than by inference. Whisper still does the actual
//  transcription; this only answers "is someone talking right now".
//
//  ECHO: the agent's own TTS is the obvious false trigger — the mic hears
//  the speakers and the agent interrupts itself in a loop. macOS voice
//  processing I/O (AEC) is the textbook fix, but ``VoiceRecorder`` documents
//  why it is disabled here: ``setVoiceProcessingEnabled`` crashes inside
//  CoreAudio when engine state is not perfectly aligned. So suppression is
//  explicit instead — ``isOutputActive`` gates detection while TTS plays,
//  plus a short tail for room reverb. It is cruder than AEC and it cannot
//  be crashed by a route change.
//

import Foundation

/// Tunables for speech-onset detection. Defaults are chosen for a desk mic
/// at arm's length; a headset wants a higher ``onsetThresholdDB``.
struct VADConfiguration: Sendable, Equatable {
    /// Frame RMS above this (dBFS) counts as possible speech.
    /// −45 dBFS sits above typical room tone and below normal speech.
    var onsetThresholdDB: Float = -45

    /// Drop below this to call it silence again. Deliberately lower than
    /// ``onsetThresholdDB``: a single threshold chatters on every dip
    /// between syllables, which would fire barge-in mid-sentence.
    var releaseThresholdDB: Float = -52

    /// Consecutive speech frames before onset is declared. At ~23 ms per
    /// frame, 3 frames ≈ 70 ms — long enough to reject a keyboard clack,
    /// short enough to stay under the 100 ms barge-in budget.
    var onsetFrames: Int = 3

    /// Consecutive quiet frames before speech is considered ended.
    /// ~700 ms, so a normal pause between clauses does not end the turn.
    var releaseFrames: Int = 30

    /// How long after TTS stops to keep ignoring the mic, covering room
    /// reverb and speaker ring-out.
    var outputTailSeconds: TimeInterval = 0.25

    /// Ignore the mic entirely while the agent is speaking. The safe
    /// default without AEC. Turning this off enables true full-duplex
    /// barge-in and requires working echo cancellation.
    var suppressWhileOutputActive: Bool = true

    static let `default` = VADConfiguration()
}

/// Frame-by-frame speech detector. Not `@MainActor`: ``process`` is called
/// from the `AVAudioEngine` render thread, where hopping to the main actor
/// would blow the real-time budget. Callbacks are dispatched to main by the
/// caller, not here.
final class SpeechEnergyDetector: @unchecked Sendable {

    enum Transition: Sendable, Equatable {
        case speechOnset
        case speechEnded
        case none
    }

    private let lock = NSLock()
    private var config: VADConfiguration
    private var speechFrames = 0
    private var quietFrames = 0
    private var inSpeech = false
    private var outputActiveUntil: Date?

    /// Most recent frame energy in dBFS, for meters. −160 = silence.
    private(set) var lastLevelDB: Float = -160

    // ── onset latency ────────────────────────────────────────────────
    //
    // Measured from the instant the installer STOPS talking to the first
    // frame of the operator's reply. Anchoring on playback end (not on the
    // question appearing) is what makes the number mean "how long they took
    // to answer" rather than "how long the prompt was".

    private var promptEndedAt: Date?
    private var measuredLatencyMs: Int?

    /// Start the response clock — call when the prompt finishes speaking.
    func markPromptEnded() {
        lock.lock(); defer { lock.unlock() }
        promptEndedAt = Date()
        measuredLatencyMs = nil
    }

    /// Milliseconds from prompt end to speech onset, or nil if unmeasured.
    var onsetLatencyMs: Int? {
        lock.lock(); defer { lock.unlock() }
        return measuredLatencyMs
    }

    // ── energy variance ──────────────────────────────────────────────
    //
    // Welford's online algorithm over per-frame dBFS while speech is
    // active. A steady voice holds a narrow band; an unsteady one — trailing
    // off, restarting, uneven emphasis — spreads. Normalised to roughly
    // 0…1 so the backend threshold is engine-independent.

    private var varianceCount = 0
    private var varianceMean: Double = 0
    private var varianceM2: Double = 0

    /// Normalised spread of speech energy, or nil with too few frames.
    ///
    /// Needs at least 5 frames (~115 ms): a standard deviation over two
    /// samples is noise, and reporting it would let a cough read as
    /// hesitance.
    var energyVariance: Float? {
        lock.lock(); defer { lock.unlock() }
        guard varianceCount >= 5 else { return nil }
        let stdDev = (varianceM2 / Double(varianceCount - 1)).squareRoot()
        // ~12 dB of spread is a lot of wobble for one utterance; scale to 1.
        return Float(min(1.0, stdDev / 12.0))
    }

    private func accumulate(_ db: Float) {
        // Ignore silence floors — they would dominate the spread and make
        // every pause look like instability.
        guard db > -100 else { return }
        varianceCount += 1
        let value = Double(db)
        let delta = value - varianceMean
        varianceMean += delta / Double(varianceCount)
        varianceM2 += delta * (value - varianceMean)
    }

    private func resetVariance() {
        varianceCount = 0
        varianceMean = 0
        varianceM2 = 0
    }

    init(configuration: VADConfiguration = .default) {
        self.config = configuration
    }

    func update(configuration: VADConfiguration) {
        lock.lock(); defer { lock.unlock() }
        config = configuration
    }

    /// Tell the detector the agent is (or just stopped) speaking.
    ///
    /// Called by the ambient loop around TTS. While active — and for
    /// ``outputTailSeconds`` after — frames are scored but cannot declare
    /// onset, so the agent's own voice never triggers its own barge-in.
    func setOutputActive(_ active: Bool) {
        lock.lock(); defer { lock.unlock() }
        if active {
            outputActiveUntil = .distantFuture
        } else {
            outputActiveUntil = Date().addingTimeInterval(config.outputTailSeconds)
        }
    }

    private var isOutputSuppressing: Bool {
        guard let until = outputActiveUntil else { return false }
        return Date() < until
    }

    /// Reset counters — use when starting a fresh listen so a previous
    /// turn's tail cannot count toward this turn's onset.
    func reset() {
        lock.lock(); defer { lock.unlock() }
        speechFrames = 0
        quietFrames = 0
        inSpeech = false
        promptEndedAt = nil
        measuredLatencyMs = nil
        resetVariance()
    }

    /// Score one buffer. Returns the transition it caused, if any.
    ///
    /// `samples` is mono float PCM in [-1, 1]; interleaved multichannel
    /// input should be passed one channel at a time (the caller already
    /// has channel 0 from the tap).
    func process(samples: UnsafePointer<Float>, count: Int) -> Transition {
        guard count > 0 else { return .none }

        // Short-time RMS → dBFS. Guard the log: a digitally silent buffer
        // is exactly 0 and log10(0) is -inf, which poisons every later
        // comparison.
        var sumSquares: Float = 0
        for index in 0..<count {
            let sample = samples[index]
            sumSquares += sample * sample
        }
        let rms = (sumSquares / Float(count)).squareRoot()
        let db = rms > 0 ? 20 * log10(rms) : -160

        lock.lock(); defer { lock.unlock() }
        lastLevelDB = db

        if config.suppressWhileOutputActive, isOutputSuppressing {
            // Keep the meter live but never transition — the energy here
            // is the agent's own voice coming back through the mic.
            speechFrames = 0
            return .none
        }

        if db >= config.onsetThresholdDB {
            speechFrames += 1
            quietFrames = 0
            accumulate(db)
            if !inSpeech, speechFrames >= config.onsetFrames {
                inSpeech = true
                if let started = promptEndedAt, measuredLatencyMs == nil {
                    // Subtract the frames it took to CONFIRM onset, so the
                    // number reports when they started talking rather than
                    // when we became sure of it.
                    let confirmMs = Double(config.onsetFrames) * 1024.0 / 44_100.0 * 1000.0
                    let elapsed = Date().timeIntervalSince(started) * 1000.0
                    measuredLatencyMs = max(0, Int(elapsed - confirmMs))
                }
                return .speechOnset
            }
        } else if db <= config.releaseThresholdDB {
            quietFrames += 1
            speechFrames = 0
            if inSpeech, quietFrames >= config.releaseFrames {
                inSpeech = false
                return .speechEnded
            }
        } else {
            // Between the two thresholds: hysteresis band. Hold state and
            // let neither counter advance, which is what stops chatter.
            speechFrames = 0
        }
        return .none
    }

    var isSpeechActive: Bool {
        lock.lock(); defer { lock.unlock() }
        return inSpeech
    }
}
