// VoiceRecorder.swift — adapted from jaeger_ai/interfaces/swift/Sources/JaegerAI/Voice/VoiceRecorder.swift
// (:57-80 mic permission, :167-279 tap/start/stop/take, :283-339 buffer handling; Jenkins Robotics).
// Changes: no ObservableObject/@Published, no monitoring mode or barge-in detector; mono mix + RMS via
// JaegerShellCore.AudioMath; captured audio is described by a mono Float32 format (the old code paired
// mono samples with the multi-channel input format); capture capped at 120 s.
// `engine.inputNode` is touched only in startRecording(), after permission is granted.
import AVFoundation
import Foundation
import JaegerShellCore

final class VoiceRecorder {
    enum VoiceError: Error, LocalizedError {
        case engineStartFailed(String)
        var errorDescription: String? { if case .engineStartFailed(let s) = self { return s }; return nil }
    }

    static var hasAudioInput: Bool { AVCaptureDevice.default(for: .audio) != nil }

    /// Prompts only when the status is .notDetermined.
    static func requestMicrophoneAccess(_ done: @escaping (Bool) -> Void) {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: done(true)
        case .notDetermined: AVCaptureDevice.requestAccess(for: .audio) { done($0) }
        default: done(false)
        }
    }

    private(set) var isRecording = false
    private(set) var level: Float = 0
    private var captureBuffer: [Float] = []
    private(set) var capturedFormat: AVAudioFormat?
    private let engine = AVAudioEngine()
    private var maxSamples = 0

    func startRecording() throws {
        guard !isRecording else { return }
        captureBuffer.removeAll(keepingCapacity: true)
        if engine.isRunning { engine.stop() }
        engine.inputNode.removeTap(onBus: 0)
        engine.reset()
        let input = engine.inputNode
        let format = input.inputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            throw VoiceError.engineStartFailed("no usable audio input device (sample rate \(format.sampleRate), channels \(format.channelCount))")
        }
        capturedFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: format.sampleRate, channels: 1, interleaved: false)
        maxSamples = Int(format.sampleRate * 120)
        input.installTap(onBus: 0, bufferSize: 1024, format: nil) { [weak self] buffer, _ in self?.handle(buffer) }
        engine.prepare()
        do { try engine.start() } catch {
            input.removeTap(onBus: 0)
            engine.stop()
            engine.reset()
            throw VoiceError.engineStartFailed("audio engine start failed — \(error.localizedDescription)")
        }
        isRecording = true
        shellLog("[shell][mic] recording — \(format.description)")
    }

    func stopRecording() {
        guard isRecording else { return }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        isRecording = false
        level = 0
        shellLog("[shell][mic] stopped — \(captureBuffer.count) samples")
    }

    func takeCapturedAudio() -> (samples: [Float], format: AVAudioFormat)? {
        guard let format = capturedFormat, !captureBuffer.isEmpty else { return nil }
        let samples = captureBuffer
        captureBuffer.removeAll(keepingCapacity: true)
        return (samples, format)
    }

    private func handle(_ buffer: AVAudioPCMBuffer) {
        guard let data = buffer.floatChannelData else { return }
        let frames = Int(buffer.frameLength)
        let channels = (0..<Int(buffer.format.channelCount)).map { Array(UnsafeBufferPointer(start: data[$0], count: frames)) }
        let mono = AudioMath.mixToMono(channels)
        let rms = AudioMath.rms(mono)
        DispatchQueue.main.async { [weak self] in
            guard let self, self.isRecording else { return }
            if self.captureBuffer.count < self.maxSamples { self.captureBuffer.append(contentsOf: mono) }
            self.level = rms
        }
    }
}
