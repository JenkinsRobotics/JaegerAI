//
//  VoiceStage.swift
//  JaegerAI / Voice / TTS
//
//  Which voice is speaking, and when it is allowed to change.
//
//  OS 1's handoff works because the operator HEARS it. States 1 and 2 use
//  a precise technical Kokoro voice; State 3 is their agent. If the agent voice
//  arrives early — the moment they answer the voice question, say — the
//  handoff line lands in a voice they have already been listening to and
//  the transition is spent before it happens.
//
//  So the stage, not the answer, decides the voice. Answering State 1
//  records a preference; it does not change what is speaking. Only
//  `.persona` does that.
//
//      State 1 (voice question)  ─┐
//      State 2 (Q2)              ─┼─► .installer   flat system voice
//      "Initializing your …"     ─┘
//      ───────────────────────────────────────────  the handoff
//      "*(clears throat)* …"     ───► .persona      calibrated voice
//

import AVFoundation
import Foundation

/// Acoustic stage of the first-boot sequence.
enum VoiceStage: String, Sendable, Equatable {
    /// Technical system guide, spoken by Kokoro with a fixed voice.
    case installer
    /// The initialized SI, calibrated to the operator's preference.
    case persona
}

/// Resolves a stage (+ preference) to concrete synthesis settings.
enum VoiceStageResolver {

    /// Natural Apple voices used only if the bundled Kokoro service is
    /// unavailable. The normal installer path never reaches these.
    static let installerVoices = [
        "com.apple.voice.premium.en-GB.Daniel",
        "com.apple.voice.enhanced.en-GB.Daniel",
        "com.apple.voice.compact.en-GB.Daniel",
    ]

    static var installerVoiceIdentifier: String {
        firstInstalled(from: installerVoices) ?? installerVoices[installerVoices.count - 1]
    }

    static let installerRate: Float = AVSpeechUtteranceDefaultSpeechRate

    /// Preferred neural voices per profile, best first. Resolution walks
    /// the list and takes the first installed one — premium voices are
    /// downloadable and absent on a clean machine, so a hard-coded single
    /// identifier would silently fall back to the installer voice and
    /// erase the whole contrast.
    static let personaVoices: [String: [String]] = [
        "female": [
            "com.apple.voice.premium.en-US.Ava",
            "com.apple.voice.enhanced.en-US.Ava",
            "com.apple.voice.enhanced.en-US.Samantha",
            "com.apple.voice.compact.en-US.Samantha",
        ],
        "male": [
            "com.apple.voice.premium.en-US.Zoe",
            "com.apple.voice.enhanced.en-US.Evan",
            "com.apple.voice.enhanced.en-US.Tom",
            "com.apple.voice.compact.en-US.Alex",
            // en-GB Daniel ships on far more machines than compact Alex,
            // which is frequently absent. Without this the male handoff
            // resolves to an uninstalled id and the synth falls back to
            // its own default — usually Samantha, i.e. the female voice.
            "com.apple.voice.compact.en-GB.Daniel",
        ],
    ]

    static let personaRate: Float = AVSpeechUtteranceDefaultSpeechRate

    /// Kokoro uses a multiplier where 1.0 is the recorded pace. Keep this
    /// separate from AVSpeechUtterance's unrelated 0...1 rate scale.
    static let installerKokoroRate: Float = 1.10
    static let personaKokoroRate: Float = 1.04

    /// Kokoro-82M voice packs, by profile.
    ///
    /// Kokoro is the persona's real voice: open-source, on-device, neural,
    /// and near-zero latency — no proprietary OS voice lock-in and none of
    /// the weight of a cloning model. The Apple identifiers above are the
    /// FALLBACK for when the bridge daemon is unreachable, not the target.
    ///
    /// The setup guide and agent deliberately share Kokoro-82M. The audible
    /// handoff comes from switching voice packs, not switching engines.
    static let installerKokoroVoice = "am_adam"
    static let kokoroVoices: [String: String] = [
        "female": "af_heart",
        "male": "am_michael",
    ]

    /// The Kokoro pack for a stage.
    static func kokoroVoice(for stage: VoiceStage, profile: String?) -> String? {
        switch stage {
        case .installer:
            return installerKokoroVoice
        case .persona:
            guard let profile else { return nil }
            return kokoroVoices[profile.lowercased()]
        }
    }

    /// The voice identifier for a stage, or nil to let the synth fall back.
    ///
    /// `profile` is ignored for `.installer` — that is the point. A
    /// recorded preference must not leak into States 1 and 2.
    static func voiceIdentifier(for stage: VoiceStage, profile: String?) -> String? {
        switch stage {
        case .installer:
            return installerVoiceIdentifier
        case .persona:
            guard let profile, let candidates = personaVoices[profile.lowercased()] else {
                return nil          // no preference recorded — system default
            }
            // Never return an uninstalled identifier: the synth would fall
            // back to the SYSTEM default, which on a stock machine is the
            // female compact voice regardless of what was asked for.
            return firstInstalled(from: candidates)
        }
    }

    static func rate(for stage: VoiceStage) -> Float {
        stage == .installer ? installerRate : personaRate
    }

    static func kokoroRate(for stage: VoiceStage) -> Float {
        stage == .installer ? installerKokoroRate : personaKokoroRate
    }

    /// First identifier actually present on this machine.
    static func firstInstalled(from candidates: [String]) -> String? {
        for identifier in candidates
        where AVSpeechSynthesisVoice(identifier: identifier) != nil {
            return identifier
        }
        return nil
    }

    /// Whether two stages would actually sound different here.
    ///
    /// Used to decide if the handoff is worth a pause. On a machine with
    /// no premium voices installed both stages can resolve to the same
    /// compact voice, and a dramatic silence before an identical voice is
    /// worse than no pause at all.
    static func isAudiblyDistinct(profile: String?) -> Bool {
        let installer = kokoroVoice(for: .installer, profile: profile)
        let persona = kokoroVoice(for: .persona, profile: profile)
        return installer != persona
    }
}
