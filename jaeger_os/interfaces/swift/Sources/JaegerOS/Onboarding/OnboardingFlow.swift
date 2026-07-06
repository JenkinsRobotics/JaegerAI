//
//  OnboardingFlow.swift
//  JaegerOS / Onboarding
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
    case welcome, character, identity, model, permissions, review
    case creating, done

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
        [.welcome, .character, .identity, .model, .permissions, .review]

    var title: String {
        switch self {
        case .welcome: return "Welcome"
        case .character: return "Character"
        case .identity: return "Identity"
        case .model: return "Model"
        case .permissions: return "Permissions"
        case .review: return "Review"
        case .creating: return "Creating"
        case .done: return "Ready"
        }
    }
}

/// The answers the flow collects. ``commandArgs`` maps them onto the
/// bridge's ``create_instance`` command — the additive v1 op pinned in
/// ``protocol_v1_fixtures.json``.
struct OnboardingAnswers: Sendable, Equatable {
    var characterId: String = ""
    var displayName: String = ""
    var role: String = ""
    var voiceId: String = ""
    /// Empty = "Use recommended" (the Python side resolves the host
    /// tier's pick, same as the wizard's default).
    var awakeModel: String = ""
    var asleepModel: String = ""
    var permissionMode: String = "confirm"

    /// Prefill identity from a picked character — the operator can still
    /// type over both fields, exactly like the CLI wizard's defaults.
    mutating func select(characterId id: String, name: String, role: String) {
        self.characterId = id
        displayName = name
        self.role = role
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
            ("display_name", displayName),
            ("role", role),
            ("voice_id", voiceId),
            ("awake_model", awakeModel),
            ("asleep_model", asleepModel),
        ]
        for (key, value) in optional {
            let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty { args[key] = trimmed }
        }
        return args
    }

    var canCreate: Bool { !characterId.isEmpty }
}

// MARK: - Bridge payloads (decoded from query results)

/// One character card from the ``characters`` query. Extra fields in the
/// payload (stats, level, …) are ignored — this flow only renders the pick.
struct OnboardingCharacter: Decodable, Identifiable, Sendable, Equatable {
    let id: String
    let name: String
    let role: String
    let icon: String?
    let card: String?
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
