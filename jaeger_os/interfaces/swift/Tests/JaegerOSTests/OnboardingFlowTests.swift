//
//  OnboardingFlowTests.swift
//  JaegerOSTests
//
//  The pure first-run flow: step machine ordering, answer → command-args
//  mapping (empties omitted so setup_wizard.py's defaults stay the single
//  source of truth), and the setup_defaults payload decoder against the
//  bridge's snake_case shape.
//

import XCTest
@testable import JaegerOS

final class OnboardingFlowTests: XCTestCase {

    // MARK: step machine

    func testStepsAdvanceInOrderAndClampAtDone() {
        var step = OnboardingStep.welcome
        var seen: [OnboardingStep] = [step]
        for _ in 0..<10 {
            step = step.next
            seen.append(step)
            if step == .done { break }
        }
        XCTAssertEqual(seen, [.welcome, .character, .identity, .model,
                              .permissions, .review, .creating, .done])
        XCTAssertEqual(OnboardingStep.done.next, .done)         // clamped
        XCTAssertEqual(OnboardingStep.welcome.previous, .welcome)
    }

    func testDottedStepsAreTheInteractiveOnes() {
        XCTAssertEqual(OnboardingStep.dotted,
                       [.welcome, .character, .identity, .model,
                        .permissions, .review])
        XCTAssertFalse(OnboardingStep.dotted.contains(.creating))
    }

    // MARK: answers → create_instance args

    func testCommandArgsAlwaysCarryRequiredTriple() {
        var a = OnboardingAnswers()
        a.characterId = "jarvis"
        let args = a.commandArgs()
        XCTAssertEqual(args["character_id"], "jarvis")
        XCTAssertEqual(args["permission_mode"], "confirm")
        XCTAssertEqual(args["interaction_mode"], "gui")
    }

    func testCommandArgsOmitEmptiesSoPythonDefaultsApply() {
        var a = OnboardingAnswers()
        a.characterId = "tars"
        a.displayName = "   "          // whitespace = unanswered
        let args = a.commandArgs()
        XCTAssertNil(args["display_name"])
        XCTAssertNil(args["role"])
        XCTAssertNil(args["awake_model"])   // = use recommended
        XCTAssertNil(args["asleep_model"])
        XCTAssertNil(args["voice_id"])
    }

    func testCommandArgsCarryTypedOverrides() {
        var a = OnboardingAnswers()
        a.select(characterId: "glados", name: "GLaDOS",
                 role: "runs the lab")
        a.displayName = "Caroline"      // typed over the prefill
        a.awakeModel = "/models/custom.gguf"
        a.permissionMode = "allow"
        let args = a.commandArgs()
        XCTAssertEqual(args["character_id"], "glados")
        XCTAssertEqual(args["display_name"], "Caroline")
        XCTAssertEqual(args["role"], "runs the lab")
        XCTAssertEqual(args["awake_model"], "/models/custom.gguf")
        XCTAssertEqual(args["permission_mode"], "allow")
    }

    func testSelectPrefillsIdentityFromCharacter() {
        var a = OnboardingAnswers()
        XCTAssertFalse(a.canCreate)
        a.select(characterId: "jarvis", name: "Jarvis",
                 role: "impeccably polite AI butler")
        XCTAssertTrue(a.canCreate)
        XCTAssertEqual(a.displayName, "Jarvis")
        XCTAssertEqual(a.role, "impeccably polite AI butler")
    }

    // MARK: payload decoding

    func testSetupDefaultsDecodesBridgeShape() throws {
        let json = """
        {"host_memory_gb": 32.0, "tier_label": "32 GB",
         "tier_description": "plenty",
         "awake": {"key": "gemma-4-e4b-it-q4_k_m",
                   "display_name": "gemma-4-E4B Q4", "size_gb": 5.3,
                   "notes": "fast", "found_locally": true,
                   "source": "JROS in-tree (dev)"},
         "asleep": {"key": "gemma-4-26b-a4b-it-qat-q4_0",
                    "display_name": "gemma-4-26B QAT", "size_gb": 14.4,
                    "notes": "deep", "found_locally": false,
                    "source": null},
         "voices": [{"id": "am_michael", "label": "Michael"}],
         "default_character": "jarvis",
         "permission_modes": [{"id": "confirm", "label": "Ask"}]}
        """.data(using: .utf8)!
        let d = try SetupDefaults.decode(json)
        XCTAssertEqual(d.tierLabel, "32 GB")
        XCTAssertEqual(d.awake.key, "gemma-4-e4b-it-q4_k_m")
        XCTAssertTrue(d.awake.foundLocally)
        XCTAssertFalse(d.asleep.foundLocally)
        XCTAssertNil(d.asleep.source)
        XCTAssertEqual(d.voices.first?.id, "am_michael")
        XCTAssertEqual(d.defaultCharacter, "jarvis")
    }

    func testCharactersQueryPayloadDecodesIgnoringExtras() throws {
        // The characters query carries more than the grid needs (stats,
        // level, …) — the decoder must skim just the card fields.
        let json = """
        [{"id": "jarvis", "name": "Jarvis", "role": "AI butler",
          "level": 3, "revision": 7, "icon": "/tmp/j.png",
          "card": "/tmp/j_card.png", "active": true, "bound": true,
          "stats": [{"key": "honesty", "val": 0.9}]}]
        """.data(using: .utf8)!
        let list = try JSONDecoder().decode([OnboardingCharacter].self,
                                            from: json)
        XCTAssertEqual(list.first?.id, "jarvis")
        XCTAssertEqual(list.first?.card, "/tmp/j_card.png")
    }
}
