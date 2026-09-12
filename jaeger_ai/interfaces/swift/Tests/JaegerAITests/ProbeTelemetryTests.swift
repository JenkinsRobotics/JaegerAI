//
//  ProbeTelemetryTests.swift
//  JaegerAITests
//
//  The acoustic half of the diagnostic. Without these the backend sees
//  hedging words but not a long silent pause — so a delayed, confident
//  one-word answer would read as confidence, which is the opposite of
//  what it is.
//

import XCTest
@testable import JaegerAI

final class ProbeTelemetryTests: XCTestCase {

    private func feed(_ d: SpeechEnergyDetector, amplitude: Float, frames: Int) {
        let samples = [Float](repeating: amplitude, count: 1024)
        for _ in 0..<frames {
            samples.withUnsafeBufferPointer {
                _ = d.process(samples: $0.baseAddress!, count: $0.count)
            }
        }
    }

    // MARK: - Onset latency

    func testLatencyIsNilBeforeTheClockIsArmed() {
        let detector = SpeechEnergyDetector()
        feed(detector, amplitude: 0.1, frames: 5)
        XCTAssertNil(detector.onsetLatencyMs, "no prompt end = nothing to measure from")
    }

    func testLatencyIsMeasuredFromPromptEnd() {
        let detector = SpeechEnergyDetector()
        detector.markPromptEnded()
        Thread.sleep(forTimeInterval: 0.25)
        feed(detector, amplitude: 0.1, frames: 5)

        let latency = detector.onsetLatencyMs
        XCTAssertNotNil(latency)
        // ~250 ms minus the ~70 ms it takes to confirm onset.
        XCTAssertGreaterThan(latency!, 100)
        XCTAssertLessThan(latency!, 500)
    }

    func testLatencySubtractsTheConfirmationWindow() {
        // The number must report when they STARTED talking, not when we
        // became sure of it — otherwise every latency is inflated by the
        // onset window and the 1800 ms threshold fires early.
        let detector = SpeechEnergyDetector()
        detector.markPromptEnded()
        feed(detector, amplitude: 0.1, frames: 5)
        XCTAssertLessThan(detector.onsetLatencyMs ?? 9999, 70,
                          "immediate speech must not report ~70 ms of latency")
    }

    func testResetClearsTheClock() {
        let detector = SpeechEnergyDetector()
        detector.markPromptEnded()
        feed(detector, amplitude: 0.1, frames: 5)
        detector.reset()
        XCTAssertNil(detector.onsetLatencyMs)
    }

    // MARK: - Energy variance

    func testVarianceIsNilWithTooFewFrames() {
        // A standard deviation over two samples is noise; reporting it
        // would let a cough read as hesitance.
        let detector = SpeechEnergyDetector()
        feed(detector, amplitude: 0.1, frames: 2)
        XCTAssertNil(detector.energyVariance)
    }

    func testSteadySpeechHasLowVariance() {
        let detector = SpeechEnergyDetector()
        feed(detector, amplitude: 0.1, frames: 20)
        let variance = detector.energyVariance
        XCTAssertNotNil(variance)
        XCTAssertLessThan(variance!, 0.1, "constant amplitude must read as steady")
    }

    func testUnevenSpeechHasHigherVariance() {
        let detector = SpeechEnergyDetector()
        for _ in 0..<6 {
            feed(detector, amplitude: 0.30, frames: 3)   // loud
            feed(detector, amplitude: 0.02, frames: 3)   // trailing off
        }
        let uneven = detector.energyVariance

        let steady = SpeechEnergyDetector()
        feed(steady, amplitude: 0.1, frames: 36)

        XCTAssertNotNil(uneven)
        XCTAssertGreaterThan(uneven!, steady.energyVariance ?? 0,
                             "wobbling delivery must read as less steady")
    }

    func testSilenceFloorsAreExcludedFromVariance() {
        // Pauses would otherwise dominate the spread and make every normal
        // sentence look unstable.
        let detector = SpeechEnergyDetector()
        feed(detector, amplitude: 0.1, frames: 10)
        let speechOnly = detector.energyVariance
        feed(detector, amplitude: 0.0, frames: 30)       // digital silence
        XCTAssertEqual(detector.energyVariance ?? 0, speechOnly ?? 0, accuracy: 0.02)
    }

    // MARK: - Coordinator surface

    @MainActor
    func testCoordinatorExposesTelemetryForThePayload() {
        let coordinator = AmbientCoordinator()
        coordinator.activate()
        coordinator.armResponseClock()
        feed(coordinator.recorder.speechDetector, amplitude: 0.1, frames: 20)

        let telemetry = coordinator.probeTelemetry
        XCTAssertNotNil(telemetry.latencyMs)
        XCTAssertNotNil(telemetry.energyVariance)
        coordinator.deactivate()
    }

    @MainActor
    func testArmingResetsTheElapsedSpeechClock() {
        // Probe 3's truncation timer must start at that probe, not carry
        // seconds over from the previous answer.
        let coordinator = AmbientCoordinator()
        coordinator.activate()
        coordinator.armResponseClock()
        XCTAssertEqual(coordinator.elapsedSpeechSeconds, 0, accuracy: 0.01)
        coordinator.deactivate()
    }

    @MainActor
    func testTypedAnswerYieldsNoAcousticsAndThatIsFine() {
        // A keyboard is a legitimate way to answer; the backend degrades
        // to text-only rather than refusing.
        let coordinator = AmbientCoordinator()
        coordinator.activate()
        let telemetry = coordinator.probeTelemetry
        XCTAssertNil(telemetry.latencyMs)
        XCTAssertNil(telemetry.energyVariance)
        coordinator.deactivate()
    }
}
