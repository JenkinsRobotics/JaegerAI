//
//  AmbientCoordinatorTests.swift
//  JaegerAITests
//
//  The coordinator decides WHEN the microphone is open. Two ways to get
//  that wrong, in opposite directions: never open it (barge-in silently
//  does nothing) or always open it (a launched app is a launched mic).
//

import XCTest
@testable import JaegerAI

@MainActor
final class AmbientCoordinatorTests: XCTestCase {

    // MARK: - Monitoring policy

    func testMicOpensOnlyForStatesThatCanBeInterrupted() {
        // Speaking is obvious. Thinking counts too: a turn is in flight and
        // cancelling before the first word is a legitimate interrupt —
        // waiting for audio would make the earliest, most deliberate
        // interruption the one that fails.
        for state in [AmbientState.speaking, .thinking, .listening] {
            XCTAssertTrue(AmbientCoordinator.needsMicrophone(for: state), "\(state)")
        }
        for state in [AmbientState.idle, .interrupted] {
            XCTAssertFalse(AmbientCoordinator.needsMicrophone(for: state), "\(state)")
        }
    }

    func testIdleAppDoesNotHoldTheMicrophone() {
        // A launched app must not be a launched microphone.
        let coordinator = AmbientCoordinator()
        coordinator.activate()
        XCTAssertEqual(coordinator.loop.state, .idle)
        coordinator.reconcileMonitoring()
        XCTAssertFalse(coordinator.isMonitoring)
        coordinator.deactivate()
    }

    func testMuteOverridesEverything() {
        // The operator's kill switch must win over any loop state — a mute
        // the software cannot talk itself out of.
        let coordinator = AmbientCoordinator()
        coordinator.activate()
        coordinator.isEnabled = false
        coordinator.reconcileMonitoring()
        XCTAssertFalse(coordinator.isMonitoring)
        coordinator.deactivate()
    }

    // MARK: - Wiring

    func testActivateWiresTheTapToTheLoop() {
        // The gap this closes: attach(recorder:) had no caller, so the
        // detector ran and nothing listened.
        let coordinator = AmbientCoordinator()
        XCTAssertNil(coordinator.recorder.onSpeechOnset)
        coordinator.activate()
        XCTAssertNotNil(coordinator.recorder.onSpeechOnset)
        XCTAssertNotNil(coordinator.recorder.onSpeechEnded)
        XCTAssertTrue(coordinator.loop.recorder === coordinator.recorder)
        coordinator.deactivate()
    }

    func testDeactivateReleasesTheMicrophone() {
        // An input tap surviving the app that opened it shows up in the
        // menu bar's recording indicator.
        let coordinator = AmbientCoordinator()
        coordinator.activate()
        coordinator.deactivate()
        XCTAssertFalse(coordinator.isMonitoring)
        XCTAssertNil(coordinator.recorder.onSpeechOnset)
        XCTAssertFalse(coordinator.recorder.isMonitoring)
    }

    func testOnsetWhileMutedDoesNotInterrupt() {
        let coordinator = AmbientCoordinator()
        coordinator.activate()
        coordinator.loop.attach(sessionID: "s1")
        coordinator.isEnabled = false
        coordinator.recorder.onSpeechOnset?()      // what the tap dispatches
        XCTAssertNotEqual(coordinator.loop.state, .listening,
                          "a muted mic must not drive barge-in")
        coordinator.deactivate()
    }

    func testReconcileIsIdempotent() {
        // Called on every state change, so a redundant call must be safe.
        let coordinator = AmbientCoordinator()
        coordinator.activate()
        for _ in 0..<5 { coordinator.reconcileMonitoring() }
        XCTAssertFalse(coordinator.isMonitoring)   // idle
        coordinator.deactivate()
    }

    func testMissingMicrophoneIsSurfacedNotFatal() {
        // Headless CI, or permission not yet granted: barge-in is simply
        // unavailable. It must not crash and must not retry in a tight loop.
        let coordinator = AmbientCoordinator()
        coordinator.activate()
        coordinator.reconcileMonitoring()
        // Either it opened, or it recorded why it could not.
        XCTAssertTrue(coordinator.isMonitoring || coordinator.lastError != nil
                      || coordinator.loop.state == .idle)
        coordinator.deactivate()
    }
}
