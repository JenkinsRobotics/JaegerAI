//
//  STTManager.swift
//  JaegerOS / Voice / STT
//
//  Thin dispatcher that picks the active STT backend and forwards
//  ``transcribe`` to it.  Today the policy is simple: prefer Whisper
//  (CoreML) if available, fall back to Apple Speech otherwise.
//  Future passes add an explicit operator override stored in a
//  settings pane.
//

import AVFoundation
import Foundation
import os

final class STTManager: @unchecked Sendable {
    static let shared = STTManager()

    let appleSpeech = AppleSpeechSTT()
    let whisper = WhisperSTT()

    private let log = Logger(subsystem: "com.jenkinsrobotics.JaegerOS",
                             category: "STTManager")

    /// The backend used for the next transcribe call.  Reads from
    /// availability today; will read from operator preference once
    /// the settings pane lands.
    var activeBackend: STTBackend {
        if whisper.isAvailable {
            return whisper
        }
        return appleSpeech
    }

    /// Transcribe captured audio with the active backend.  Forwards
    /// directly — the indirection exists so the chat view-model
    /// doesn't have to know which backend is wired today.
    func transcribe(
        samples: [Float],
        format: AVAudioFormat,
        completion: @escaping @Sendable (Result<STTResult, Error>) -> Void
    ) {
        let backend = activeBackend
        let approxSec = format.sampleRate > 0
            ? samples.count / Int(format.sampleRate)
            : 0
        log.info("transcribe via \(backend.displayName, privacy: .public) — \(samples.count) samples / \(approxSec)s")
        backend.transcribe(
            samples: samples,
            format: format,
            completion: completion
        )
    }

    func cancel() {
        activeBackend.cancel()
    }
}
