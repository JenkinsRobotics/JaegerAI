//
//  VoiceStageTests.swift
//  JaegerAITests
//
//  The OS 1 handoff is an acoustic event. These pin the one property that
//  makes it work: the installer voice must be unaffected by the operator's
//  answer, so the change at State 3 is the first time they hear it.
//

import AVFoundation
import XCTest
@testable import JaegerAI

final class VoiceStageTests: XCTestCase {

    // MARK: - The invariant

    func testInstallerVoiceIgnoresTheRecordedPreference() {
        // THE test. If answering "female" changes what States 1–2 sound
        // like, the handoff is spent a turn early and State 3 arrives in a
        // voice the operator has already been listening to.
        let neutral = VoiceStageResolver.voiceIdentifier(for: .installer, profile: nil)
        for profile in ["female", "male", "FEMALE", "Male"] {
            XCTAssertEqual(
                VoiceStageResolver.voiceIdentifier(for: .installer, profile: profile),
                neutral,
                "installer voice changed for profile \(profile)"
            )
        }
    }

    func testInstallerRateIsIndependentOfProfile() {
        XCTAssertEqual(VoiceStageResolver.rate(for: .installer),
                       VoiceStageResolver.installerRate)
        XCTAssertNotEqual(VoiceStageResolver.rate(for: .installer),
                          VoiceStageResolver.rate(for: .persona),
                          "installer and persona must differ in prosody too")
    }

    func testPersonaVoiceRespondsToTheProfile() {
        let female = VoiceStageResolver.voiceIdentifier(for: .persona, profile: "female")
        let male = VoiceStageResolver.voiceIdentifier(for: .persona, profile: "male")
        XCTAssertNotNil(female)
        XCTAssertNotNil(male)
        XCTAssertNotEqual(female, male)
    }

    func testPersonaFallsBackToSystemDefaultWithoutAPreference() {
        // A refused or unanswered voice question must not crash or pin a
        // gendered voice the operator never chose.
        XCTAssertNil(VoiceStageResolver.voiceIdentifier(for: .persona, profile: nil))
        XCTAssertNil(VoiceStageResolver.voiceIdentifier(for: .persona, profile: "purple"))
    }

    // MARK: - Resolution robustness

    func testPersonaResolutionPrefersInstalledVoices() {
        // Premium voices are downloadable and absent on a clean machine.
        // Resolution must walk the candidate list rather than pin one id,
        // or it silently degrades to the installer voice and erases the
        // contrast entirely.
        for profile in ["female", "male"] {
            let resolved = VoiceStageResolver.voiceIdentifier(for: .persona, profile: profile)
            XCTAssertNotNil(resolved)
            let candidates = VoiceStageResolver.personaVoices[profile]!
            XCTAssertTrue(candidates.contains(resolved!))
        }
    }

    func testInstallerVoiceIsAlwaysInstalled() {
        // Samantha compact ships on every macOS; if this ever resolves nil
        // the installer would be silent on a clean machine.
        XCTAssertNotNil(
            AVSpeechSynthesisVoice(identifier: VoiceStageResolver.installerVoiceIdentifier)
        )
    }

    func testFirstInstalledSkipsMissingIdentifiers() {
        let resolved = VoiceStageResolver.firstInstalled(from: [
            "com.apple.voice.premium.en-US.DefinitelyNotInstalled",
            VoiceStageResolver.installerVoiceIdentifier,
        ])
        XCTAssertEqual(resolved, VoiceStageResolver.installerVoiceIdentifier)
    }

    func testFirstInstalledReturnsNilWhenNothingIsPresent() {
        XCTAssertNil(VoiceStageResolver.firstInstalled(from: ["not.a.real.voice"]))
    }

    // MARK: - Manager routing

    @MainActor
    func testManagerDefaultsToPersonaForOrdinaryOperation() {
        // Every session after first boot must use the calibrated voice
        // without anyone setting a stage.
        XCTAssertEqual(TTSManager().voiceStage, .persona)
    }

    @MainActor
    func testEnteringInstallerStageDoesNotDiscardThePreference() {
        // The preference is RECORDED during States 1–2 and applied later.
        // Dropping it on stage entry would lose the answer entirely.
        let tts = TTSManager()
        tts.preferredVoiceProfile = "female"
        tts.enterVoiceStage(.installer)
        XCTAssertEqual(tts.voiceStage, .installer)
        XCTAssertEqual(tts.preferredVoiceProfile, "female")
    }

    @MainActor
    func testHandoffSwapsStageAndAdoptsThePreference() {
        let tts = TTSManager()
        tts.preferredVoiceProfile = "male"
        tts.enterVoiceStage(.installer)
        tts.enterVoiceStage(.persona)

        XCTAssertEqual(tts.voiceStage, .persona)
        XCTAssertEqual(
            tts.appleSpeech.voiceIdentifier,
            VoiceStageResolver.voiceIdentifier(for: .persona, profile: "male")
        )
    }

    @MainActor
    func testReenteringTheSameStageIsANoOp() {
        // Guards the audio flush: re-entering would stop a mid-sentence
        // utterance for no reason and clip the installer's own speech.
        let tts = TTSManager()
        tts.enterVoiceStage(.installer)
        let before = tts.appleSpeech.voiceIdentifier
        tts.enterVoiceStage(.installer)
        XCTAssertEqual(tts.appleSpeech.voiceIdentifier, before)
    }
}
