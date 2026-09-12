//
//  VoiceStage.swift
//  JaegerAI / Voice / TTS
//
//  Which voice is speaking, and when it is allowed to change.
//
//  OS 1's handoff works because the operator HEARS it. States 1 and 2 are
//  a flat system installer; State 3 is their SI. If the persona voice
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
    /// Neutral system baseline. Deliberately unremarkable.
    case installer
    /// The initialized SI, calibrated to the operator's preference.
    case persona
}

/// Resolves a stage (+ preference) to concrete synthesis settings.
enum VoiceStageResolver {

    /// Installer candidates, best first.
    ///
    /// Eloquence leads deliberately. It is Apple's old formant synthesiser
    /// — unmistakably machine-like — which is exactly right for a system
    /// installer and guarantees the State 3 swap to a natural voice is
    /// heard as a change rather than inferred.
    ///
    /// It also solves a real problem on stock hardware: premium and
    /// enhanced voices are downloadable and frequently absent, so an
    /// installer pinned to compact Samantha resolves to the SAME voice the
    /// female persona falls back to, and the handoff becomes silent-
    /// identical. Eloquence ships with the OS, so the contrast survives a
    /// machine with nothing else installed.
    static let installerVoices = [
        "com.apple.eloquence.en-US.Reed",
        "com.apple.eloquence.en-US.Sandy",
        "com.apple.voice.compact.en-US.Samantha",
    ]

    static var installerVoiceIdentifier: String {
        firstInstalled(from: installerVoices) ?? installerVoices[installerVoices.count - 1]
    }

    /// Slightly under the default. Reads as measured and machine-like,
    /// and leaves headroom for the persona to sound more natural.
    static let installerRate: Float = 0.48

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
        let installer = voiceIdentifier(for: .installer, profile: profile)
        let persona = voiceIdentifier(for: .persona, profile: profile)
        return installer != persona
    }
}
