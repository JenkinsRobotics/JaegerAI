//
//  OnboardingFlowTests.swift
//  JaegerAITests
//
//  The pure first-run flow: step machine ordering, answer → command-args
//  mapping (empties omitted so setup_wizard.py's defaults stay the single
//  source of truth), and the setup_defaults payload decoder against the
//  bridge's snake_case shape.
//

import XCTest
@testable import JaegerAI

final class OnboardingFlowTests: XCTestCase {

    func testSelectionCarriesProviderWithModel() {
        var answers = OnboardingAnswers()
        answers.awakeModel = "gemini-test:cloud"
        answers.awakeProvider = "ollama-local"
        XCTAssertEqual(answers.commandArgs()["awake_provider"], "ollama-local")
        XCTAssertEqual(answers.commandArgs()["awake_model"], "gemini-test:cloud")
    }

    private func catalog() throws -> ModelMatrixPayload {
        let json = #"{"host_memory_gb":32,"tier_label":"test","tier_description":"test","recommended_primary_key":"test.gguf","recommended_fallback_key":"test.gguf","providers":[{"id":"in-process","name":"Local","kind":"local","status":"available","endpoint":"local","requires_key":false,"env_var":"","description":"Local"}],"models":[]}"#
        return try ModelMatrixPayload.decode(Data(json.utf8))
    }

    @MainActor
    func testCatalogFailureCannotAdvanceOrCreate() {
        let model = OnboardingModel(agent: AgentBridge())
        model.loading = false
        model.catalogError = "Catalog unavailable"
        model.advance()
        XCTAssertEqual(model.step, .welcome)
        XCTAssertFalse(model.canContinue)
    }

    @MainActor
    func testChangingProviderClearsPreviousModel() {
        let model = OnboardingModel(agent: AgentBridge())
        model.answers.awakeProvider = "in-process"
        model.answers.awakeModel = "old.gguf"
        model.selectProvider("openai")
        XCTAssertEqual(model.answers.awakeProvider, "openai")
        XCTAssertEqual(model.answers.awakeModel, "")
    }

    func testSetupLaunchNeverAttachesToAlreadyLoadedAgent() {
        XCTAssertEqual(BridgeProcess.launchArguments(instance: "os-1", setupOnly: true),
                       ["bridge", "os-1", "--setup"])
        XCTAssertEqual(BridgeProcess.launchArguments(instance: nil, setupOnly: false),
                       ["bridge", "--attach"])
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
        XCTAssertNil(args["voice_profile"])
        XCTAssertNil(args["interaction_posture"])
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

    // MARK: name precedence — pin > character preset; user edit > both
    // (the lilith/anakin bug: the CLI's pinned name must survive a
    // character pick instead of being silently clobbered).

    func testCliPinWinsOverCharacterPreset() {
        var a = OnboardingAnswers()
        a.pinnedName = "lilith"
        a.displayName = "lilith"          // seeded from suggested_name
        a.select(characterId: "anakin_skywalker", name: "Anakin Skywalker",
                 role: "fallen jedi")
        XCTAssertEqual(a.displayName, "lilith",
                       "a CLI pin must survive a character pick")
        XCTAssertEqual(a.characterId, "anakin_skywalker")   // persona still applies
    }

    func testUserEditWinsOverALaterCharacterPick() {
        var a = OnboardingAnswers()
        a.select(characterId: "jarvis", name: "Jarvis", role: "butler")
        a.displayName = "Ted"
        a.displayNameEdited = true        // the IdentityStep binding sets this
        a.select(characterId: "hal9000", name: "HAL 9000", role: "sentient computer")
        XCTAssertEqual(a.displayName, "Ted",
                       "an operator's own edit must survive re-picking a character")
    }

    func testCharacterPresetStillFillsAnUntouchedUnpinnedField() {
        var a = OnboardingAnswers()
        a.select(characterId: "jarvis", name: "Jarvis", role: "butler")
        XCTAssertEqual(a.displayName, "Jarvis")
        // Browsing to a different card before typing anything follows the
        // latest pick — this is the ordinary (no pin, no edit) path.
        a.select(characterId: "hal9000", name: "HAL 9000", role: "sentient computer")
        XCTAssertEqual(a.displayName, "HAL 9000")
    }

    func testCommandArgsSendsPinnedNameVerbatim() {
        var a = OnboardingAnswers()
        a.pinnedName = "lilith"
        a.select(characterId: "anakin_skywalker", name: "Anakin Skywalker",
                 role: "fallen jedi")
        let args = a.commandArgs()
        XCTAssertEqual(args["name"], "lilith")
        XCTAssertEqual(args["character_id"], "anakin_skywalker")
    }

    func testCommandArgsOmitNameWhenNoPin() {
        var a = OnboardingAnswers()
        a.select(characterId: "anakin_skywalker", name: "Anakin Skywalker",
                 role: "fallen jedi")
        let args = a.commandArgs()
        XCTAssertNil(args["name"],
                    "no pin: the server slugs the dir from display_name")
        XCTAssertEqual(args["display_name"], "Anakin Skywalker")
    }

    // MARK: payload decoding

    func testSetupDefaultsDecodesBridgeShape() throws {
        let json = """
        {"host_memory_gb": 32.0, "tier_label": "32 GB",
         "tier_description": "plenty",
         "awake": {"key": "gemma-4-e4b-it-q4_k_m",
                   "display_name": "gemma-4-E4B Q4", "size_gb": 5.3,
                   "notes": "fast", "found_locally": true,
                   "source": "JaegerAI in-tree (dev)"},
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
          "description": "A composed systems companion",
          "voice_tone": "measured and natural",
          "voice_id": "bm_fable",
          "backstory": "Built to manage a complex household.",
          "highlights": ["Mindset: anticipates needs", "Voice: measured"],
          "level": 3, "revision": 7, "icon": "/tmp/j.png",
          "card": "/tmp/j_card.png", "active": true, "bound": true,
          "stats": [{"key": "honesty", "val": 0.9}]}]
        """.data(using: .utf8)!
        let list = try JSONDecoder().decode([OnboardingCharacter].self,
                                            from: json)
        XCTAssertEqual(list.first?.id, "jarvis")
        XCTAssertEqual(list.first?.card, "/tmp/j_card.png")
        XCTAssertEqual(list.first?.description, "A composed systems companion")
        XCTAssertEqual(list.first?.voiceTone, "measured and natural")
        XCTAssertEqual(list.first?.voiceId, "bm_fable")
        XCTAssertEqual(list.first?.backstory, "Built to manage a complex household.")
        XCTAssertEqual(list.first?.highlights?.count, 2)
    }
}
