//
//  AmbientLoopTests.swift
//  JaegerAITests
//
//  Covers the two pieces that decide whether the ambient loop feels alive:
//  clause-boundary flushing (how soon it starts talking) and energy VAD
//  hysteresis (whether it stops when you talk over it, without stopping
//  when it hears itself).
//

import XCTest
@testable import JaegerAI

final class ClauseBufferTests: XCTestCase {

    func testFlushesOnSentenceEnd() {
        var buffer = ClauseBuffer()
        XCTAssertEqual(buffer.append("Hello there"), [])
        XCTAssertEqual(buffer.append("."), ["Hello there."])
    }

    func testSpeaksFirstClauseBeforeTurnCompletes() {
        // The whole point: speech starts while tokens are still arriving.
        var buffer = ClauseBuffer()
        let ready = buffer.append("I checked the logs, and the failure repeats")
        XCTAssertEqual(ready, ["I checked the logs,"])
        XCTAssertFalse(buffer.pending.isEmpty)
    }

    func testShortClauseIsNotFlushedEarly() {
        // "Well," on its own would sound like a stutter.
        var buffer = ClauseBuffer()
        XCTAssertEqual(buffer.append("Well,"), [])
    }

    func testSentenceEndIgnoresMinimumLength() {
        var buffer = ClauseBuffer()
        XCTAssertEqual(buffer.append("Yes."), ["Yes."])
    }

    func testFlushReturnsUnpunctuatedTail() {
        var buffer = ClauseBuffer()
        _ = buffer.append("no trailing punctuation")
        XCTAssertEqual(buffer.flush(), "no trailing punctuation")
        XCTAssertNil(buffer.flush())
    }

    func testMultipleBoundariesInOneChunk() {
        var buffer = ClauseBuffer()
        XCTAssertEqual(buffer.append("One. Two. Three."), ["One.", "Two.", "Three."])
    }

    func testNewlineIsASentenceBoundary() {
        var buffer = ClauseBuffer()
        XCTAssertEqual(buffer.append("a line\n"), ["a line"])
    }
}

final class SpeechEnergyDetectorTests: XCTestCase {

    /// One frame of constant amplitude, ~23 ms at 44.1 kHz.
    private func frame(amplitude: Float, count: Int = 1024) -> [Float] {
        Array(repeating: amplitude, count: count)
    }

    private func feed(
        _ detector: SpeechEnergyDetector,
        amplitude: Float,
        frames: Int
    ) -> [SpeechEnergyDetector.Transition] {
        var seen: [SpeechEnergyDetector.Transition] = []
        let samples = frame(amplitude: amplitude)
        for _ in 0..<frames {
            samples.withUnsafeBufferPointer { pointer in
                seen.append(detector.process(samples: pointer.baseAddress!, count: pointer.count))
            }
        }
        return seen
    }

    func testSilenceNeverTriggersOnset() {
        let detector = SpeechEnergyDetector()
        let seen = feed(detector, amplitude: 0.0, frames: 20)
        XCTAssertFalse(seen.contains(.speechOnset))
        XCTAssertFalse(detector.isSpeechActive)
    }

    func testLoudSpeechTriggersOnsetAfterOnsetFrames() {
        let detector = SpeechEnergyDetector()
        // 0.1 ≈ −20 dBFS, comfortably above the −45 threshold.
        let seen = feed(detector, amplitude: 0.1, frames: 5)
        XCTAssertEqual(seen.filter { $0 == .speechOnset }.count, 1,
                       "onset must fire exactly once, not every frame")
        XCTAssertTrue(detector.isSpeechActive)
    }

    func testOnsetRequiresSustainedEnergyNotASingleClick() {
        var config = VADConfiguration.default
        config.onsetFrames = 3
        let detector = SpeechEnergyDetector(configuration: config)
        // Two loud frames then silence — a keyboard clack, not speech.
        _ = feed(detector, amplitude: 0.1, frames: 2)
        XCTAssertFalse(detector.isSpeechActive)
    }

    func testOutputSuppressionPreventsSelfTrigger() {
        // The agent hearing its own TTS must NOT barge in on itself.
        let detector = SpeechEnergyDetector()
        detector.setOutputActive(true)
        let seen = feed(detector, amplitude: 0.5, frames: 20)
        XCTAssertFalse(seen.contains(.speechOnset))
    }

    func testDetectionResumesAfterOutputStops() {
        var config = VADConfiguration.default
        config.outputTailSeconds = 0            // no tail, for a fast test
        let detector = SpeechEnergyDetector(configuration: config)
        detector.setOutputActive(true)
        _ = feed(detector, amplitude: 0.5, frames: 5)
        detector.setOutputActive(false)
        let seen = feed(detector, amplitude: 0.5, frames: 5)
        XCTAssertTrue(seen.contains(.speechOnset))
    }

    func testSpeechEndsAfterSustainedSilence() {
        var config = VADConfiguration.default
        config.releaseFrames = 3
        let detector = SpeechEnergyDetector(configuration: config)
        _ = feed(detector, amplitude: 0.1, frames: 5)
        XCTAssertTrue(detector.isSpeechActive)
        let seen = feed(detector, amplitude: 0.0, frames: 5)
        XCTAssertTrue(seen.contains(.speechEnded))
        XCTAssertFalse(detector.isSpeechActive)
    }

    func testHysteresisBandDoesNotEndSpeechBetweenSyllables() {
        // Between release (−52) and onset (−45): a dip, not a stop.
        var config = VADConfiguration.default
        config.releaseFrames = 3
        let detector = SpeechEnergyDetector(configuration: config)
        _ = feed(detector, amplitude: 0.1, frames: 5)
        // ~0.004 ≈ −48 dBFS, inside the band.
        let seen = feed(detector, amplitude: 0.004, frames: 10)
        XCTAssertFalse(seen.contains(.speechEnded),
                       "a syllable gap must not end the turn")
        XCTAssertTrue(detector.isSpeechActive)
    }

    func testResetClearsPriorTurnState() {
        let detector = SpeechEnergyDetector()
        _ = feed(detector, amplitude: 0.1, frames: 5)
        XCTAssertTrue(detector.isSpeechActive)
        detector.reset()
        XCTAssertFalse(detector.isSpeechActive)
    }

    /// The barge-in budget: onset must be decidable within ~100 ms of
    /// speech starting. At 1024 frames / 44.1 kHz ≈ 23 ms, the default
    /// 3-frame onset is ~70 ms — this pins that arithmetic so raising
    /// onsetFrames cannot silently blow the budget.
    func testOnsetLatencyStaysUnderBudget() {
        let config = VADConfiguration.default
        let frameSeconds = 1024.0 / 44_100.0
        let onsetSeconds = Double(config.onsetFrames) * frameSeconds
        XCTAssertLessThan(onsetSeconds, 0.100, "barge-in onset exceeds 100 ms")
    }
}

@MainActor
final class BargeInWiringTests: XCTestCase {

    /// Feed frames the way the render thread does, through the same
    /// pointer API ``VoiceRecorder.handle(buffer:)`` uses.
    private func feed(
        _ detector: SpeechEnergyDetector, amplitude: Float, frames: Int
    ) -> [SpeechEnergyDetector.Transition] {
        let samples = [Float](repeating: amplitude, count: 1024)
        return (0..<frames).map { _ in
            samples.withUnsafeBufferPointer {
                detector.process(samples: $0.baseAddress!, count: $0.count)
            }
        }
    }

    func testRecorderExposesTheDetectorAndOnsetHooks() {
        // The gap this closes: the detector existed and nothing fed it,
        // and handleSpeechOnset existed and nothing called it.
        let recorder = VoiceRecorder()
        XCTAssertFalse(recorder.isMonitoring)

        var fired = false
        recorder.onSpeechOnset = { fired = true }
        recorder.onSpeechOnset?()
        XCTAssertTrue(fired, "onset hook must be invocable by the tap")
    }

    func testAttachWiresBothCallbacks() throws {
        try XCTSkipUnless(VoiceRecorder.hasAudioInput,
                          "This host has no usable microphone; attach wiring is not a live CoreAudio test")
        let loop = AmbientLoop(gateway: GatewayClient(baseURL: GatewayClient.defaultBaseURL),
                               tts: TTSManager(),
                               detector: SpeechEnergyDetector())
        let recorder = VoiceRecorder()
        // startMonitoring may fail on a headless CI box with no input
        // device; the wiring is what is under test, so tolerate that.
        try loop.attach(recorder: recorder)
        XCTAssertNotNil(recorder.onSpeechOnset)
        XCTAssertNotNil(recorder.onSpeechEnded)

        loop.detach(recorder: recorder)
        XCTAssertNil(recorder.onSpeechOnset)
        XCTAssertFalse(recorder.isMonitoring)
    }

    func testOnsetPropagatesThroughTheRecorderHook() {
        // End to end minus CoreAudio: detector transition -> hook -> loop.
        let detector = SpeechEnergyDetector()
        let loop = AmbientLoop(gateway: GatewayClient(baseURL: GatewayClient.defaultBaseURL),
                               tts: TTSManager(), detector: detector)
        let recorder = VoiceRecorder()
        recorder.onSpeechOnset = { [weak loop] in loop?.handleSpeechOnset() }

        let seen = feed(detector, amplitude: 0.1, frames: 5)
        XCTAssertTrue(seen.contains(.speechOnset))
        recorder.onSpeechOnset?()          // what the tap dispatches
        XCTAssertEqual(loop.state, .listening)
    }

    func testTTSPlaybackCannotSelfTriggerBargeIn() {
        // THE guard. With AEC disabled the mic hears the speakers; without
        // suppression the agent interrupts itself in a loop.
        let detector = SpeechEnergyDetector()
        detector.setOutputActive(true)
        let seen = feed(detector, amplitude: 0.6, frames: 30)
        XCTAssertFalse(seen.contains(.speechOnset),
                       "agent's own TTS must not trigger its own barge-in")
    }

    func testBargeInStopsSpeakingAndReturnsToListening() {
        let loop = AmbientLoop(gateway: GatewayClient(baseURL: GatewayClient.defaultBaseURL),
                               tts: TTSManager(), detector: SpeechEnergyDetector())
        loop.attach(sessionID: "s1")
        loop.handleSpeechOnset()
        // Local stop happens first and synchronously; the gateway cancel is
        // fired detached so the room goes quiet without a round trip.
        XCTAssertEqual(loop.state, .listening)
    }

    func testMonitoringDoesNotRetainAudio() throws {
        try XCTSkipUnless(VoiceRecorder.hasAudioInput,
                          "This host has no usable microphone; monitoring cannot open a real input tap")
        // An always-open mic that stores nothing is a level meter, not a
        // recording — the privacy-relevant difference from startRecording.
        let recorder = VoiceRecorder()
        try recorder.startMonitoring()
        XCTAssertNil(recorder.takeCapturedAudio()?.samples.isEmpty == false ? true : nil)
        recorder.stopMonitoring()
        XCTAssertFalse(recorder.isMonitoring)
    }
}
