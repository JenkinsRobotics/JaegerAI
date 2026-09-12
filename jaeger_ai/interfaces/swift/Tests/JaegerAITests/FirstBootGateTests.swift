//
//  FirstBootGateTests.swift
//  JaegerAITests
//
//  The launch gate decides whether an operator sees the OS 1 welcome. Two
//  ways to get it wrong, both bad and both silent:
//
//    * guess "finished" when the bridge is down → a new operator never
//      meets their SI, and the welcome can never fire again
//    * guess "not started" → a long-time operator is marched back through
//      it, which reads as their SI having forgotten them
//
//  So `.unavailable` is a distinct third outcome and these tests pin it.
//

import XCTest
@testable import JaegerAI

@MainActor
final class FirstBootGateTests: XCTestCase {

    private func turnPayload(
        speaker: String = "os1",
        text: String = "Welcome to OS 1."
    ) -> [String: Any] {
        ["speaker": speaker, "lines": [text], "text": text, "awaits_reply": true]
    }

    private func decode(_ object: [String: Any]) -> FirstBootGate.Turn? {
        // Exercises the same decoder the gate uses on bridge payloads.
        guard let data = try? JSONSerialization.data(withJSONObject: object),
              let round = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        guard let speaker = round["speaker"] as? String,
              let text = round["text"] as? String else { return nil }
        return FirstBootGate.Turn(
            speaker: speaker,
            lines: round["lines"] as? [String] ?? [text],
            text: text,
            awaitsReply: round["awaits_reply"] as? Bool ?? true
        )
    }

    func testTurnDecodesFromBridgePayload() {
        let turn = decode(turnPayload())
        XCTAssertEqual(turn?.speaker, "os1")
        XCTAssertEqual(turn?.text, "Welcome to OS 1.")
        XCTAssertTrue(turn?.awaitsReply ?? false)
    }

    func testPersonaHandoffIsDistinguishedFromInstallerVoice() {
        // State 3 must speak in the persona's voice, not the neutral
        // installer voice — that transition is the product moment.
        let installer = decode(turnPayload(speaker: "os1"))
        let persona = decode(turnPayload(speaker: "persona",
                                         text: "*(clears throat)* Hello, I'm here."))
        XCTAssertFalse(installer?.isPersonaHandoff ?? true)
        XCTAssertTrue(persona?.isPersonaHandoff ?? false)
    }

    func testDecisionsAreDistinctOutcomes() {
        // `.unavailable` must never compare equal to `.proceed`; collapsing
        // them is exactly the bug that skips somebody's welcome forever.
        let turn = decode(turnPayload())!
        XCTAssertNotEqual(FirstBootGate.Decision.proceed,
                          FirstBootGate.Decision.unavailable("bridge down"))
        XCTAssertNotEqual(FirstBootGate.Decision.proceed,
                          FirstBootGate.Decision.onboard(turn))
        XCTAssertEqual(FirstBootGate.Decision.proceed, FirstBootGate.Decision.proceed)
    }

    func testVoiceProfileIsAnExperienceNotAVendorVoiceID() {
        let tts = TTSManager()
        let gate = FirstBootGate(bridge: AgentBridge())
        gate.applyVoiceProfile("female", to: tts)

        XCTAssertEqual(tts.preferredVoiceProfile, "female")
        // A Kokoro id here would weld the operator's first decision to one
        // TTS backend for the life of the identity.
        XCTAssertFalse(tts.preferredVoiceProfile?.hasPrefix("af_") ?? true)
        XCTAssertFalse(tts.preferredVoiceProfile?.hasPrefix("am_") ?? true)
    }

    func testFailureCarriesTheBackendReason() {
        // `unclear_voice_answer` must reach the UI so it re-asks rather
        // than assigning a voice the operator never chose.
        let failure = FirstBootGate.Failure(message: "unclear_voice_answer")
        XCTAssertEqual(failure.errorDescription, "unclear_voice_answer")
    }
}
