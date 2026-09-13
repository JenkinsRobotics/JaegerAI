//
//  OnboardingFlow.swift
//  JaegerAI / Onboarding
//
//  The PURE first-run flow pieces — step machine, collected answers,
//  and the decodable payloads for the bridge's setup queries. No UI,
//  no process state: everything here is unit-testable (see
//  OnboardingFlowTests). The window/views live in OnboardingWindow.swift.
//
//  Contract: the wizard logic stays in Python (setup_wizard.py); this
//  flow only COLLECTS answers and ships them over the bridge's
//  ``create_instance`` command. Empty answers are omitted so the Python
//  side applies the exact same defaults the CLI wizard's Enter-through
//  path does (identity from the character sheet, models from the host
//  tier recommendation).
//

import Foundation

/// One screen per step, iOS-new-device style. ``creating``/``done`` sit
/// past the interactive run and don't count toward the progress dots.
enum OnboardingStep: Int, CaseIterable, Sendable, Comparable {
    case welcome, architecture, character, calibration, identity, model, permissions, review
    case creating, firstContact, done

    static func < (lhs: OnboardingStep, rhs: OnboardingStep) -> Bool {
        lhs.rawValue < rhs.rawValue
    }

    var next: OnboardingStep {
        OnboardingStep(rawValue: rawValue + 1) ?? .done
    }

    var previous: OnboardingStep {
        OnboardingStep(rawValue: rawValue - 1) ?? .welcome
    }

    /// Steps that show as progress dots (the interactive ones).
    static let dotted: [OnboardingStep] =
        [.welcome, .architecture, .character, .identity, .model, .permissions, .review, .firstContact]

    var title: String {
        switch self {
        case .welcome: return "Welcome"
        case .architecture: return "Architecture"
        case .character: return "Character"
        case .calibration: return "Calibration"
        case .identity: return "Identity"
        case .model: return "Model"
        case .permissions: return "Permissions"
        case .review: return "Review"
        case .creating: return "Creating"
        case .firstContact: return "First Contact"
        case .done: return "Ready"
        }
    }
}

/// The answers the flow collects. ``commandArgs`` maps them onto the
/// bridge's ``create_instance`` command — the additive v1 op pinned in
/// ``protocol_v1_fixtures.json``.
struct OnboardingAnswers: Sendable, Equatable {
    var userName: String = ""
    var setupPath: String = "preset"
    var voiceProfile: String = ""
    var interactionPosture: String = ""
    var customPrimeDirective: String = ""
    var characterId: String = ""
    var displayName: String = ""
    var role: String = ""
    var voiceId: String = ""
    /// Empty = "Use recommended" (the Python side resolves the host
    /// tier's pick, same as the wizard's default).
    var awakeModel: String = ""
    var awakeProvider: String = ""
    var asleepModel: String = ""
    var permissionMode: String = "confirm"

    /// The CLI-pinned name (bridge's ``suggested_name``, e.g. ``./jaeger
    /// agent create lilith``), or empty when none. Seeded once at
    /// ``loadCatalog`` time; wins over every character preset until the
    /// operator types over the Name field.
    var pinnedName: String = ""
    /// True once the operator has typed into the Name field — an edit
    /// always wins over both the pin and any later character pick.
    var displayNameEdited: Bool = false

    /// Prefill identity from a picked character. Precedence (the operator
    /// contract): a user edit or a CLI pin always wins over the preset —
    /// selecting a character only fills the (still-blank, still-untouched)
    /// Name field, it never clobbers a name the operator already has.
    mutating func select(characterId id: String, name: String, role: String) {
        self.characterId = id
        self.role = role
        if pinnedName.isEmpty && !displayNameEdited {
            displayName = name
        }
    }

    /// The ``create_instance`` args. Blank optionals are OMITTED so the
    /// single source of truth for defaults stays in setup_wizard.py.
    func commandArgs() -> [String: String] {
        var args: [String: String] = [
            "character_id": characterId,
            "permission_mode": permissionMode,
            // The native app IS the desktop surface.
            "interaction_mode": "gui",
        ]
        let optional: [(String, String)] = [
            ("user_name", userName),
            ("custom_prime_directive", customPrimeDirective),
            ("display_name", displayName),
            ("role", role),
            ("voice_id", voiceId),
            ("voice_profile", voiceProfile),
            ("interaction_posture", interactionPosture),
            ("awake_model", awakeModel),
            ("awake_provider", awakeProvider),
            ("asleep_model", asleepModel),
        ]
        for (key, value) in optional {
            let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty { args[key] = trimmed }
        }
        let pin = pinnedName.trimmingCharacters(in: .whitespacesAndNewlines)
        if !pin.isEmpty { args["name"] = pin }
        return args
    }

    var canCreate: Bool { !characterId.isEmpty || setupPath == "custom_test" }
}

// MARK: - Bridge payloads (decoded from query results)

/// One character card from the ``characters`` query. Extra fields in the
/// payload (stats, level, …) are ignored — this flow only renders the pick.
struct OnboardingCharacter: Decodable, Identifiable, Sendable, Equatable {
    let id: String
    let name: String
    let role: String
    let description: String?
    let voiceTone: String?
    let voiceId: String?
    let backstory: String?
    let highlights: [String]?
    let icon: String?
    let card: String?

    enum CodingKeys: String, CodingKey {
        case id, name, role, description, highlights, icon, card
        case voiceTone = "voice_tone"
        case voiceId = "voice_id"
        case backstory
    }
}

/// The ``setup_defaults`` query — host tier + the recommended model pair
/// + voices, the same data the CLI wizard prints in Step 2.
struct SetupDefaults: Decodable, Sendable, Equatable {
    struct ModelPick: Decodable, Sendable, Equatable {
        let key: String
        let displayName: String
        let sizeGb: Double
        let notes: String
        let foundLocally: Bool
        let source: String?
    }

    struct Voice: Decodable, Sendable, Identifiable, Equatable {
        let id: String
        let label: String
    }

    let hostMemoryGb: Double
    let tierLabel: String
    let tierDescription: String
    let awake: ModelPick
    let asleep: ModelPick
    let voices: [Voice]
    let defaultCharacter: String?

    /// Decoder matching the bridge's snake_case payloads.
    static func decode(_ data: Data) throws -> SetupDefaults {
        let dec = JSONDecoder()
        dec.keyDecodingStrategy = .convertFromSnakeCase
        return try dec.decode(SetupDefaults.self, from: data)
    }
}

/// One provider descriptor from ``onboarding_model_matrix``.
struct ModelProvider: Decodable, Sendable, Identifiable, Equatable {
    let id: String
    let name: String
    let kind: String           // "local" or "cloud"
    var status: String         // "connected", "available", "configured", "needs_key", "offline"
    let endpoint: String
    let requiresKey: Bool
    let envVar: String
    let description: String
}

/// One model descriptor from ``onboarding_model_matrix``.
struct DiscoveredModelEntry: Decodable, Sendable, Identifiable, Equatable {
    let id: String
    let name: String
    let provider: String
    let providerLabel: String
    let location: String       // "local" or "cloud"
    let sizeGb: Double?
    let contextLength: Int?
    let role: String           // "realtime", "deep_think", "general", "vision", "embedding"
    let speed: String
    let description: String
    let isRecommendedPrimary: Bool
    let isRecommendedFallback: Bool
    let isConfigured: Bool?
    let isChatModel: Bool?
}

/// The configured neural stack currently active in config.yaml.
struct ConfiguredStack: Decodable, Sendable, Equatable {
    let instanceName: String
    var primaryModel: String
    var primaryProvider: String
    var primaryEndpoint: String
    var fallbackModel: String
    var fallbackProvider: String
    var coderModel: String
    var ttsEngine: String
    var ttsVoice: String
    var ttsLang: String
    var sttEngine: String
    var sttMode: String
    var sttFastModel: String
    var sttAccurateModel: String
    var visionModel: String?
    var embeddingModel: String?
    var voiceEnabled: Bool
}

/// Simple option for TTS voices and STT models.
struct VoiceOption: Decodable, Sendable, Identifiable, Equatable {
    let id: String
    let label: String
}

struct SttModelOption: Decodable, Sendable, Identifiable, Equatable {
    let id: String
    let label: String
}

/// The full provider and model matrix for OS 1 onboarding.
struct ModelMatrixPayload: Decodable, Sendable, Equatable {
    let hostMemoryGb: Double
    let tierLabel: String
    let tierDescription: String
    let recommendedPrimaryKey: String
    let recommendedFallbackKey: String
    let providers: [ModelProvider]
    let models: [DiscoveredModelEntry]
    let configured: ConfiguredStack?
    let availableTtsVoices: [VoiceOption]?
    let availableSttModels: [SttModelOption]?

    static func decode(_ data: Data) throws -> ModelMatrixPayload {
        let dec = JSONDecoder()
        dec.keyDecodingStrategy = .convertFromSnakeCase
        return try dec.decode(ModelMatrixPayload.self, from: data)
    }
}
