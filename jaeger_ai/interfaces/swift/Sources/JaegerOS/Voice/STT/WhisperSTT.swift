//
//  WhisperSTT.swift
//  JaegerOS / Voice / STT
//
//  Whisper.cpp + CoreML backend — the production STT target per the
//  0.3.0 pivot plan.  Currently a SCAFFOLD: the protocol surface is
//  here so the rest of the app (settings UI, A/B picker, telemetry)
//  can be built against it, but the actual inference is stubbed out
//  pending the next session's integration work.
//
//  What this file will become:
//
//    1. Bundle whisper.cpp as a SwiftPM dependency
//       (https://github.com/ggerganov/whisper.cpp — has Swift Package
//       support via the ``whisper`` product).  Build flag
//       ``WHISPER_COREML=1`` enables the CoreML encoder.
//
//    2. Convert a Whisper model variant (large-v3 or distil-small)
//       to CoreML using whisper.cpp's ``models/convert-whisper-to-
//       coreml.py`` script.  Bundle the .mlmodelc file as a SwiftPM
//       resource (~200-500 MB depending on size).
//
//    3. Implement ``transcribe()`` here:
//       * resample input to 16kHz mono Float32 (Whisper's required
//         input format) using ``AVAudioConverter``
//       * load the model once at init, reuse across calls
//       * run inference on a background DispatchQueue
//       * fire completion with the result
//
//    4. Add a settings toggle (Apple Speech / Whisper / auto-best)
//       so the operator can A/B them on real audio.
//
//  Today: ``isAvailable`` returns false (no model bundled), so the
//  STT manager falls through to AppleSpeechSTT.  When the next-
//  session work finishes, ``isAvailable`` flips to true once the
//  bundled .mlmodelc is detected and the rest lights up.
//

import AVFoundation
import Foundation
import os

final class WhisperSTT: STTBackend, @unchecked Sendable {
    let displayName: String = "Whisper (CoreML, ANE)"

    /// True only when the bundled model + whisper.cpp library are
    /// present.  Returns false at v1 so the manager falls through
    /// to AppleSpeechSTT.  Flips to true once the model bundle
    /// lands in a follow-up commit.
    var isAvailable: Bool {
        // Lookup is layered so the next-session integration only has
        // to update this single check:
        //   1. Is the CoreML model file present in Bundle.module?
        //   2. Is the whisper.cpp dynamic library loadable?
        //   3. Did we successfully load the model into memory?
        Bundle.module.url(
            forResource: "whisper-coreml-encoder",
            withExtension: "mlmodelc"
        ) != nil
    }

    private let log = Logger(subsystem: "com.jenkinsrobotics.JaegerOS",
                             category: "WhisperSTT")

    // MARK: - STTBackend

    func transcribe(
        samples: [Float],
        format: AVAudioFormat,
        completion: @escaping @Sendable (Result<STTResult, Error>) -> Void
    ) {
        // Until the model + library bundle lands, this path is a
        // hard "unavailable" so callers fall back to Apple Speech.
        // The error message points at the next-session work so a
        // future me reading this in stack traces knows what's missing.
        log.error("WhisperSTT.transcribe called but backend is a stub — model bundling lands in a follow-up session")
        DispatchQueue.main.async {
            completion(.failure(STTError.unavailable(
                "WhisperSTT scaffold — model + whisper.cpp library "
                + "not bundled yet. See WhisperSTT.swift header for "
                + "the next-session integration plan."
            )))
        }
    }

    func cancel() {
        // Will cancel the inference task once we're running real
        // whisper.cpp.  No-op for the stub.
    }
}
