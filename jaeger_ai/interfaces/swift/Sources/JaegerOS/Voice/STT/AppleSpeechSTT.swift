//
//  AppleSpeechSTT.swift
//  JaegerOS / Voice / STT
//
//  SFSpeechRecognizer backend — Apple's on-device speech recognition.
//  Default STT for v1 because:
//
//    * Comes with macOS — no model bundling, no whisper.cpp build
//    * Free, no API key, runs locally
//    * Good quality for dictation in English
//    * Works on the ANE on Apple Silicon (Apple uses it for Siri)
//
//  Limitations vs. the Whisper backend that lands next:
//
//    * English-first; other languages work but Whisper Large-V3 is
//      meaningfully better on non-English audio
//    * No tuning knobs (model size, beam width, etc.)
//    * Daily request limits exist on some macOS versions for the
//      cloud-flavoured recognizer; we force on-device mode so it
//      doesn't bite us
//

import AVFoundation
import Foundation
import Speech
import os

final class AppleSpeechSTT: STTBackend, @unchecked Sendable {
    let displayName: String = "Apple Speech (on-device)"

    var isAvailable: Bool {
        // Authorization state + recognizer availability for the
        // operator's current locale.  Both have to be green.
        let auth = SFSpeechRecognizer.authorizationStatus()
        guard auth == .authorized || auth == .notDetermined else {
            return false
        }
        guard let recognizer = SFSpeechRecognizer() else { return false }
        return recognizer.isAvailable
    }

    private let log = Logger(subsystem: "com.jenkinsrobotics.JaegerOS",
                             category: "AppleSpeechSTT")
    private var currentTask: SFSpeechRecognitionTask?

    // MARK: - STTBackend

    func transcribe(
        samples: [Float],
        format: AVAudioFormat,
        completion: @escaping @Sendable (Result<STTResult, Error>) -> Void
    ) {
        requestAuthorizationIfNeeded { [weak self] authResult in
            guard let self else { return }
            switch authResult {
            case .failure(let err):
                DispatchQueue.main.async { completion(.failure(err)) }
            case .success:
                self.startTranscription(
                    samples: samples,
                    format: format,
                    completion: completion
                )
            }
        }
    }

    func cancel() {
        currentTask?.cancel()
        currentTask = nil
    }

    // MARK: - Authorization

    private func requestAuthorizationIfNeeded(
        completion: @escaping @Sendable (Result<Void, Error>) -> Void
    ) {
        let status = SFSpeechRecognizer.authorizationStatus()
        switch status {
        case .authorized:
            completion(.success(()))
        case .denied:
            completion(.failure(STTError.authorizationDenied(
                "enable in System Settings → Privacy & Security → Speech Recognition"
            )))
        case .restricted:
            completion(.failure(STTError.authorizationDenied(
                "restricted on this device"
            )))
        case .notDetermined:
            SFSpeechRecognizer.requestAuthorization { newStatus in
                if newStatus == .authorized {
                    completion(.success(()))
                } else {
                    completion(.failure(STTError.authorizationDenied(
                        "denied at the system prompt"
                    )))
                }
            }
        @unknown default:
            completion(.failure(STTError.authorizationDenied(
                "unknown authorization state"
            )))
        }
    }

    // MARK: - Transcription

    private func startTranscription(
        samples: [Float],
        format: AVAudioFormat,
        completion: @escaping @Sendable (Result<STTResult, Error>) -> Void
    ) {
        guard let recognizer = SFSpeechRecognizer() else {
            DispatchQueue.main.async {
                completion(.failure(STTError.unavailable(
                    "no SFSpeechRecognizer for current locale"
                )))
            }
            return
        }
        guard recognizer.isAvailable else {
            DispatchQueue.main.async {
                completion(.failure(STTError.unavailable(
                    "recognizer reports unavailable"
                )))
            }
            return
        }

        let request = SFSpeechAudioBufferRecognitionRequest()
        // ``true`` = strictly on-device — no cloud round-trip, no
        // request-limit roulette.  The ANE handles this on Apple
        // Silicon.
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = false

        let started = Date()
        currentTask = recognizer.recognitionTask(with: request) {
            [weak self] result, error in
            guard let self else { return }
            // We only fire the completion on the final result so the
            // caller doesn't see partial-then-final two-hit behavior.
            if let error {
                self.log.error("recognition error: \(error.localizedDescription, privacy: .public)")
                DispatchQueue.main.async {
                    completion(.failure(STTError.recognitionFailed(
                        error.localizedDescription
                    )))
                }
                self.currentTask = nil
                return
            }
            guard let result, result.isFinal else { return }

            let best = result.bestTranscription
            let text = best.formattedString.trimmingCharacters(
                in: .whitespacesAndNewlines
            )
            let confidence = best.segments.isEmpty
                ? nil
                : best.segments.map(\.confidence).reduce(0, +)
                    / Float(best.segments.count)
            let elapsed = Date().timeIntervalSince(started)
            self.log.info("recognized \(text.count) chars in \(elapsed)s, confidence=\(String(describing: confidence))")

            if text.isEmpty {
                DispatchQueue.main.async {
                    completion(.failure(STTError.noSpeechDetected))
                }
            } else {
                let out = STTResult(
                    text: text,
                    confidence: confidence,
                    elapsedSeconds: elapsed
                )
                DispatchQueue.main.async { completion(.success(out)) }
            }
            self.currentTask = nil
        }

        // Feed the captured samples in.  SFSpeechAudioBufferRecognitionRequest
        // wants an AVAudioPCMBuffer; we build one from the Float
        // sample array we already have.
        if let buffer = makeBuffer(samples: samples, format: format) {
            request.append(buffer)
        } else {
            log.error("failed to build PCM buffer for recognizer")
        }
        request.endAudio()
    }

    /// Wrap a ``[Float]`` mono sample array into an ``AVAudioPCMBuffer``
    /// at the captured format.  Returns nil on allocation failure.
    private func makeBuffer(samples: [Float], format: AVAudioFormat) -> AVAudioPCMBuffer? {
        let frameCapacity = AVAudioFrameCount(samples.count)
        guard let buffer = AVAudioPCMBuffer(
            pcmFormat: format,
            frameCapacity: frameCapacity
        ) else { return nil }
        buffer.frameLength = frameCapacity
        guard let channelData = buffer.floatChannelData else { return nil }
        // Mono — write into channel 0.
        samples.withUnsafeBufferPointer { src in
            channelData[0].update(from: src.baseAddress!, count: samples.count)
        }
        return buffer
    }
}
