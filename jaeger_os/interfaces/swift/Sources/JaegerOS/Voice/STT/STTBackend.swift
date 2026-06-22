//
//  STTBackend.swift
//  JaegerOS / Voice / STT
//
//  Speech-to-text backend protocol.  Lets us swap STT implementations
//  without ripping up the call sites — VoiceRecorder hands the
//  captured PCM buffer to whichever backend is currently configured,
//  the backend returns transcribed text, the chat surface drops it in
//  the composer.
//
//  Two backends ship in 0.3.0:
//
//    * ``AppleSpeechSTT`` — SFSpeechRecognizer (on-device, free,
//      English-first, ships with macOS).  Default for v1; the
//      simplest path to a working voice loop.
//    * ``WhisperSTT`` — whisper.cpp + CoreML, ANE-accelerated.
//      Production target per the 0.3.0 pivot plan (2-3× faster STT
//      than CPU pywhispercpp).  Lands in a follow-up session with
//      model bundling + CoreML conversion.
//
//  Both implement the same protocol so the operator can A/B them via
//  a setting once both are real.  Today only Apple Speech is wired.
//

import AVFoundation
import Foundation

/// Outcome of a transcription request.
struct STTResult: Sendable {
    /// The most-likely transcribed text.  Empty string is valid (the
    /// recognizer heard nothing intelligible) — callers should check.
    let text: String

    /// Per-segment confidence the recognizer reported, if available.
    /// 0…1; ``nil`` when the backend doesn't surface a number.
    let confidence: Float?

    /// Wall-clock seconds the transcription pass took.  Useful for
    /// telemetry + A/B comparisons between backends.
    let elapsedSeconds: Double
}

/// What a STT backend has to provide.  Callback-based on purpose —
/// we already ate two Swift-6 strict-concurrency crashes in the
/// voice path; keeping this side of the API plain GCD avoids
/// re-introducing the same hazards.
protocol STTBackend: AnyObject {
    /// Display name shown in the future settings UI ("Apple Speech",
    /// "Whisper (CoreML)", etc.).
    var displayName: String { get }

    /// True if the backend is available on this machine right now
    /// (model present, authorization granted, hardware capable).
    /// Cheap to call — used to populate the picker.
    var isAvailable: Bool { get }

    /// Transcribe a captured PCM buffer.  ``samples`` is mono Float32
    /// at ``format.sampleRate``.  The completion fires on the main
    /// queue with either a result or an error.  ``@Sendable``
    /// because backends do the recognition on background queues and
    /// hop to main before firing.
    func transcribe(
        samples: [Float],
        format: AVAudioFormat,
        completion: @escaping @Sendable (Result<STTResult, Error>) -> Void
    )

    /// Cancel any in-flight recognition.  No-op if nothing is in
    /// flight.  Used when the operator hits the mic again before the
    /// previous transcription finishes.
    func cancel()
}

/// Shared error type so callers can surface a uniform "transcription
/// failed" line regardless of which backend produced it.
enum STTError: Error, LocalizedError {
    case unavailable(String)
    case authorizationDenied(String)
    case recognitionFailed(String)
    case noSpeechDetected

    var errorDescription: String? {
        switch self {
        case .unavailable(let s): return "STT unavailable — \(s)"
        case .authorizationDenied(let s): return "speech recognition denied — \(s)"
        case .recognitionFailed(let s): return "recognition failed — \(s)"
        case .noSpeechDetected: return "didn't catch any speech"
        }
    }
}
