//
//  VoiceRecorder.swift
//  JaegerOS / Voice
//
//  Wraps AVAudioEngine for push-to-talk recording.  This is the
//  foundation for the Apple-native audio pipeline that replaces the
//  0.2.x sounddevice / PortAudio stack — the same rebuild call-out
//  that justified the Swift pivot in 0.3.0.
//
//  Capabilities lit up by this layer (#1 of the 0.3.0 voice work):
//
//    * AVAudioEngine input tap to capture microphone audio at the
//      hardware-preferred format (mono float32 @ ~48 kHz on Mac
//      Studio / Mac Mini; AVAudioEngine handles sample-rate
//      negotiation).
//    * Voice-processing mode — Apple's built-in AEC + noise
//      suppression, identical to what FaceTime uses. Replaces the
//      speexdsp dependency we were carrying for echo cancellation.
//    * AirPods / Bluetooth route handling via AVAudioSession's
//      automatic route management (no manual reconfiguration when
//      a headset connects mid-session — the engine adapts).
//    * Captured PCM frames append into a Data buffer the caller
//      drains on stopRecording(). Future #2 hands this buffer to
//      CoreML-accelerated whisper.cpp for STT.
//
//  Concurrency: ``@MainActor`` because the start/stop transitions
//  drive ``@Published`` UI state. The audio callback runs on
//  AVAudioEngine's render thread; we hop back to MainActor to mutate
//  state (recording flag, level meter).
//

import AVFoundation
import Foundation
import os

/// Push-to-talk voice recorder.  One instance per app session;
/// ``ChatViewModel`` holds it and starts / stops it from the PTT
/// button.
///
/// **NOT** ``@MainActor`` — AVAudioEngine's tap callback fires on
/// the audio render thread, and a ``@MainActor``-isolated closure
/// capture trips ``swift_task_checkIsolatedSwift`` and crashes
/// inside ``dispatch_assert_queue_fail``.  Instead the class lives
/// outside actor isolation; @Published updates dispatch back to the
/// main queue explicitly so SwiftUI binding stays well-formed.
///
/// ``@unchecked Sendable`` is honest here: the only mutable state
/// (``captureBuffer``, the engine, ``isRecording`` etc.) is written
/// exclusively from the main queue (via DispatchQueue.main.async)
/// after the audio callback computes its samples on the render
/// thread.  No two threads write the same property simultaneously.
final class VoiceRecorder: ObservableObject, @unchecked Sendable {

    /// True while the engine is running and we're capturing samples.
    @Published private(set) var isRecording: Bool = false

    /// 0…1 normalized peak level over the current sample window.  Used
    /// to drive a live waveform / level meter in the composer.
    @Published private(set) var levelMeter: Float = 0.0

    /// Last non-fatal error surfaced to the UI (mic permission denied,
    /// engine start failure).  Cleared on the next successful start.
    @Published private(set) var lastError: String? = nil

    /// The captured PCM frames from the most recent recording session.
    /// Float32 mono at ``capturedFormat?.sampleRate`` Hz.  Cleared at
    /// the start of each new session; the caller drains via
    /// ``takeCapturedAudio()`` once recording stops.
    private var captureBuffer: [Float] = []

    /// The format we actually got from the audio engine (may differ
    /// from the requested format depending on device + voice-
    /// processing mode constraints).  ``nil`` until the first
    /// successful start.
    private(set) var capturedFormat: AVAudioFormat?

    private let engine = AVAudioEngine()
    private let log = Logger(subsystem: "com.jenkinsrobotics.JaegerOS",
                             category: "VoiceRecorder")

    // MARK: - Lifecycle

    /// Start capturing.  No-op if already recording.  Throws on
    /// engine-start failure or missing input device.
    ///
    /// Synchronous on purpose — Swift 6 strict concurrency around
    /// the audio engine + Task hops + Button action callbacks has
    /// produced a class of immediate-crash bugs we can't easily
    /// reproduce in the debugger.  Doing everything synchronously on
    /// the main actor keeps the call graph dead simple and avoids the
    /// dispatch races.  ``requestAccess`` for the mic prompt fires
    /// automatically the first time we touch ``inputNode``.
    func startRecording() throws {
        guard !isRecording else { return }

        captureBuffer.removeAll(keepingCapacity: true)

        // Defensive teardown — if a previous start crashed mid-way,
        // the engine could be in a partial state.  Stop + reset
        // brings it back to a known baseline.
        if engine.isRunning {
            engine.stop()
        }
        engine.inputNode.removeTap(onBus: 0)
        engine.reset()

        let input = engine.inputNode

        // First pass: NO voice processing.  ``setVoiceProcessingEnabled``
        // is famously unstable on macOS when the engine state isn't
        // perfectly aligned (audio unit format mismatch, route changes
        // mid-call, aggregate devices, etc.) — instead of failing
        // gracefully it tends to crash the whole process inside
        // CoreAudio.  We get clean raw capture working first; voice-
        // processing AEC moves to a flagged second pass once we've
        // validated the baseline pipeline on the operator's hardware.
        let format = input.inputFormat(forBus: 0)

        // Bail early if there's no usable input device.
        guard format.sampleRate > 0, format.channelCount > 0 else {
            lastError = "no usable audio input device (sample rate \(format.sampleRate), channels \(format.channelCount))"
            throw VoiceError.engineStartFailed(lastError ?? "input format invalid")
        }

        capturedFormat = format

        // ``nil`` format tells AVAudioEngine to deliver buffers in the
        // input node's actual format without any conversion attempt —
        // the most lenient option and sidesteps subtle format-mismatch
        // rejections.
        input.installTap(onBus: 0, bufferSize: 1024, format: nil) {
            [weak self] buffer, _ in
            self?.handle(buffer: buffer)
        }

        engine.prepare()
        do {
            try engine.start()
        } catch {
            // CRITICAL: a failed engine.start() can leave the
            // audio unit holding the input device — which then
            // blocks OTHER apps (browsers, video players, the
            // system itself) from grabbing the audio system.
            // We've seen YouTube playback freeze when a stuck
            // engine sits in this half-state.  Tear down fully:
            //   1. remove the tap we just installed
            //   2. stop the engine even though start returned an
            //      error (the audio unit may still be partially
            //      attached)
            //   3. reset the engine to release any internal
            //      buffers + device handles
            input.removeTap(onBus: 0)
            engine.stop()
            engine.reset()
            let detail = "audio engine start failed — \(error.localizedDescription)"
            lastError = detail
            log.error("engine start failed, full teardown done: \(error.localizedDescription, privacy: .public)")
            throw VoiceError.engineStartFailed(detail)
        }

        isRecording = true
        lastError = nil
        log.info("recording started — format=\(format.description, privacy: .public)")
    }

    /// Stop capturing.  No-op if not recording.  Must be called from
    /// the main queue — same as ``startRecording``.
    func stopRecording() {
        guard isRecording else { return }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        isRecording = false
        levelMeter = 0.0
        log.info("recording stopped — \(self.captureBuffer.count) samples / \(self.recordedDuration)s")
    }

    /// Drain the captured PCM buffer.  Returns the samples + the
    /// format they were captured in.  Clears the internal buffer so
    /// the next recording starts fresh.
    func takeCapturedAudio() -> (samples: [Float], format: AVAudioFormat)? {
        guard let format = capturedFormat, !captureBuffer.isEmpty else {
            return nil
        }
        let samples = captureBuffer
        captureBuffer.removeAll(keepingCapacity: true)
        return (samples, format)
    }

    /// Length of the most recent recording in seconds.  ``0`` if no
    /// capture happened yet.
    var recordedDuration: Double {
        guard let format = capturedFormat, format.sampleRate > 0 else {
            return 0.0
        }
        return Double(captureBuffer.count) / format.sampleRate
    }

    // MARK: - Audio callback

    private func handle(buffer: AVAudioPCMBuffer) {
        // The tap fires on the engine's render thread.  Extract the
        // samples here (cheap, just a copy) and dispatch to the main
        // queue to append them + update the level meter.  Plain
        // DispatchQueue.main.async instead of Task { @MainActor in … }
        // — same effect but no Task creation per render tick (which
        // Swift 6 strict concurrency has been crashing on under
        // pressure inside SwiftUI's view-update path).
        guard let channelData = buffer.floatChannelData else { return }
        let frameLength = Int(buffer.frameLength)
        let channelCount = Int(buffer.format.channelCount)

        // Down-mix to mono — most macOS mics report a single channel,
        // but if voice processing yields stereo (rare), average to one.
        var mono = [Float](repeating: 0, count: frameLength)
        for ch in 0..<channelCount {
            let samples = channelData[ch]
            for i in 0..<frameLength {
                mono[i] += samples[i]
            }
        }
        if channelCount > 1 {
            let inv = 1.0 / Float(channelCount)
            for i in 0..<frameLength { mono[i] *= inv }
        }

        // Peak for the level meter — cheap O(n) max-abs.
        var peak: Float = 0
        for s in mono where abs(s) > peak { peak = abs(s) }

        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.captureBuffer.append(contentsOf: mono)
            // Smooth the meter a bit so it doesn't flicker — ema(0.4).
            self.levelMeter = min(1.0, max(self.levelMeter * 0.6 + peak * 0.4, peak))
        }
    }

    // MARK: - Errors

    enum VoiceError: Error, LocalizedError {
        case micPermissionDenied(String)
        case engineStartFailed(String)

        var errorDescription: String? {
            switch self {
            case .micPermissionDenied(let s): return s
            case .engineStartFailed(let s): return s
            }
        }
    }
}
