// AppleSpeechSTT.swift — adapted from jaeger_ai/interfaces/swift/Sources/JaegerAI/Voice/STT/AppleSpeechSTT.swift:34-215
// (Jenkins Robotics). Changes: on-device recognition is required only when the recognizer supports it
// (the old code always required it and failed on unsupported locales); shell log tags.
@preconcurrency import AVFoundation
import Foundation
import Speech

final class AppleSpeechSTT: STTBackend, @unchecked Sendable {
    let displayName = "Apple Speech"
    private var currentTask: SFSpeechRecognitionTask?

    var isAvailable: Bool {
        let auth = SFSpeechRecognizer.authorizationStatus()
        guard auth == .authorized || auth == .notDetermined else { return false }
        return SFSpeechRecognizer()?.isAvailable ?? false
    }

    func transcribe(samples: [Float], format: AVAudioFormat,
                    completion: @escaping @Sendable (Result<STTResult, Error>) -> Void) {
        requestAuthorizationIfNeeded { [weak self] auth in
            guard let self else { return }
            switch auth {
            case .failure(let err): DispatchQueue.main.async { completion(.failure(err)) }
            case .success: self.startTranscription(samples: samples, format: format, completion: completion)
            }
        }
    }

    func cancel() {
        currentTask?.cancel()
        currentTask = nil
    }

    /// Prompts only when the status is .notDetermined (i.e. only from a real mic.stop).
    private func requestAuthorizationIfNeeded(completion: @escaping @Sendable (Result<Void, Error>) -> Void) {
        switch SFSpeechRecognizer.authorizationStatus() {
        case .authorized: completion(.success(()))
        case .denied:
            completion(.failure(STTError.authorizationDenied("enable in System Settings → Privacy & Security → Speech Recognition")))
        case .restricted: completion(.failure(STTError.authorizationDenied("restricted on this device")))
        case .notDetermined:
            SFSpeechRecognizer.requestAuthorization { status in
                completion(status == .authorized ? .success(()) : .failure(STTError.authorizationDenied("denied at the system prompt")))
            }
        @unknown default: completion(.failure(STTError.authorizationDenied("unknown authorization state")))
        }
    }

    private func startTranscription(samples: [Float], format: AVAudioFormat,
                                    completion: @escaping @Sendable (Result<STTResult, Error>) -> Void) {
        guard let recognizer = SFSpeechRecognizer() else {
            DispatchQueue.main.async { completion(.failure(STTError.unavailable("no SFSpeechRecognizer for current locale"))) }
            return
        }
        guard recognizer.isAvailable else {
            DispatchQueue.main.async { completion(.failure(STTError.unavailable("recognizer reports unavailable"))) }
            return
        }
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.requiresOnDeviceRecognition = recognizer.supportsOnDeviceRecognition
        request.shouldReportPartialResults = false
        let started = Date()
        currentTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self else { return }
            if let error {
                shellLog("[shell][stt] recognition error: \(error.localizedDescription)")
                DispatchQueue.main.async { completion(.failure(STTError.recognitionFailed(error.localizedDescription))) }
                self.currentTask = nil
                return
            }
            guard let result, result.isFinal else { return }
            let best = result.bestTranscription
            let text = best.formattedString.trimmingCharacters(in: .whitespacesAndNewlines)
            let confidence = best.segments.isEmpty ? nil : best.segments.map(\.confidence).reduce(0, +) / Float(best.segments.count)
            let elapsed = Date().timeIntervalSince(started)
            shellLog("[shell][stt] recognized \(text.count) chars in \(String(format: "%.2f", elapsed))s (on-device \(request.requiresOnDeviceRecognition))")
            DispatchQueue.main.async {
                completion(text.isEmpty ? .failure(STTError.noSpeechDetected)
                    : .success(STTResult(text: text, confidence: confidence, elapsedSeconds: elapsed)))
            }
            self.currentTask = nil
        }
        if let buffer = makeBuffer(samples: samples, format: format) { request.append(buffer) }
        else { shellLog("[shell][stt] failed to build PCM buffer") }
        request.endAudio()
    }

    private func makeBuffer(samples: [Float], format: AVAudioFormat) -> AVAudioPCMBuffer? {
        let capacity = AVAudioFrameCount(samples.count)
        guard capacity > 0, let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: capacity),
              let channel = buffer.floatChannelData else { return nil }
        buffer.frameLength = capacity
        samples.withUnsafeBufferPointer { src in channel[0].update(from: src.baseAddress!, count: samples.count) }
        return buffer
    }
}
