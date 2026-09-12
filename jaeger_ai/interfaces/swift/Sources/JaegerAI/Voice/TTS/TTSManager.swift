//
//  TTSManager.swift
//  JaegerAI / Voice / TTS
//
//  Thin dispatcher that picks the active TTS backend and forwards
//  ``speak`` to it.  Mirrors STTManager.  Owns a @Published
//  ``isSpeaking`` SwiftUI views can watch (the menu bar shows a
//  speaker indicator when audio's playing, e.g.).
//
//  Engine routing: the agent's REAL voice is Kokoro on the Python side
//  (the ``speak`` tool / TTS node, using the active character's
//  configured voice_id).  When the bridge is up and config.yaml's
//  ``voice.speech_engine`` says "kokoro" (the default), ``speak`` routes
//  through the bridge's additive ``speak`` command so the chat window's
//  speaker button sounds like the agent, not like Siri.  AppleSpeechSynth
//  remains the local engine ("apple") and the automatic fallback whenever
//  the bridge is down / still booting.  Exposing the engine picker in the
//  settings HUD is a follow-up (AgentSettingsHUD is operator-owned).
//

import Foundation
import os

@MainActor
final class TTSManager: ObservableObject {
    static let shared = TTSManager()

    @Published private(set) var isSpeaking: Bool = false

    /// Operator preference — when off, the auto-speak path in
    /// ChatViewModel short-circuits.  Default OFF: the agent has its
    /// own Kokoro tool that decides when to vocalize — auto-speaking
    /// every reply would compete with that agency.  Operators who
    /// want every reply spoken (accessibility, eyes-off contexts)
    /// flip this on from the menu bar.  The per-bubble manual speak
    /// button is the primary surface for "speak this specific reply."
    @Published var autoSpeakEnabled: Bool = false

    /// The voice experience the operator chose at OS 1 first boot —
    /// ``"male"`` or ``"female"``, or nil before they have answered.
    ///
    /// Deliberately an experience rather than a vendor voice id: the
    /// capability router maps it onto Apple / Kokoro / OpenAI / whatever is
    /// installed. Storing ``am_michael`` here would weld the operator's
    /// very first decision to one TTS backend for the life of the identity.
    /// Persisted by the backend in `first_boot.yaml`; mirrored here so the
    /// speech layer can honour it without a round trip on every utterance.
    ///
    /// Recording this does NOT change what is currently speaking — see
    /// ``voiceStage``. During first boot the preference is held until the
    /// handoff, because the change of voice IS the handoff.
    @Published var preferredVoiceProfile: String?

    /// Which voice is speaking right now.
    ///
    /// ``.installer`` for OS 1 States 1–2 (flat system baseline, ignores
    /// ``preferredVoiceProfile``) and ``.persona`` from the handoff line
    /// onward. Defaults to ``.persona`` so ordinary operation — every
    /// session after first boot — uses the calibrated voice without
    /// anyone having to set a stage.
    @Published private(set) var voiceStage: VoiceStage = .persona

    /// Move to a new acoustic stage, flushing cleanly.
    ///
    /// Stops any in-flight utterance at a word boundary rather than
    /// ``.immediate``: cutting mid-phoneme produces the click the handoff
    /// must not have. The synth is left idle before the next utterance is
    /// built, so the new voice starts from silence instead of splicing
    /// onto a half-drained buffer.
    func enterVoiceStage(_ stage: VoiceStage) {
        guard stage != voiceStage else { return }
        appleSpeech.finishCurrentUtteranceCleanly()
        voiceStage = stage
        appleSpeech.applyStage(stage, profile: preferredVoiceProfile)
    }

    let appleSpeech = AppleSpeechSynth()

    private let log = Logger(subsystem: "com.jenkinsrobotics.JaegerAI",
                             category: "TTSManager")

    /// The backend used for the next speak call.  Future settings
    /// override could rotate this to a different backend.
    var activeBackend: TTSBackend { appleSpeech }

    /// Speak ``text``.  Strips Markdown first so the synthesizer
    /// doesn't read asterisks aloud.  Routes to the agent's Kokoro
    /// voice over the bridge when connected + configured (the
    /// default); falls back to the local Apple synth otherwise.
    /// No-op if ``autoSpeakEnabled`` is false (the call site passes
    /// the operator-preference check in; this method respects it).
    func speak(_ text: String) {
        let body = TTSText.plainForSpeech(text)
        NSLog("[TTSManager] speak called — input=\(text.count) chars, afterStrip=\(body.count) chars")
        guard !body.isEmpty else {
            NSLog("[TTSManager] body empty after markdown strip — skipping")
            return
        }
        Task { @MainActor [weak self] in
            guard let self else { return }
            // States 1–2 are the installer and NEVER reach the neural
            // engine: routing them through Kokoro would make the handoff
            // inaudible, which is the whole point of the stage split.
            if self.voiceStage == .installer {
                self.speakLocally(body)
                return
            }
            if await self.speakViaAgent(body) { return }
            // Apple is the fallback, reached only when the bridge daemon is
            // unreachable or refuses — not a co-equal backend.
            self.speakLocally(body)
        }
    }

    /// Try the agent's real voice: the bridge's ``speak`` command runs
    /// Kokoro on the Python side with the ACTIVE character's configured
    /// voice.  Returns false — caller falls back to the Apple synth —
    /// when the bridge is down, config.yaml's ``voice.speech_engine`` is
    /// "apple", or the command is refused (agent still booting).
    private func speakViaAgent(_ body: String) async -> Bool {
        let bridge = AgentBridge.shared
        guard bridge.isConnected else { return false }
        // The engine choice lives in config.yaml (voice.speech_engine,
        // default "kokoro") and is read over the EXISTING config query on
        // every utterance — a config edit applies on the next speak, no
        // restart.  An unreadable config defaults to kokoro: the bridge is
        // up, so prefer the agent's real voice.
        let cfg = await bridge.query("config")
        if cfg.ok, let json = cfg.json,
           let obj = (try? JSONSerialization.jsonObject(with: json)) as? [String: Any],
           let engine = obj["speech_engine"] as? String,
           engine == "apple" {
            return false
        }
        log.info("speak via bridge/kokoro — \(body.count) chars")
        // The Python side accepts and synthesizes fire-and-forget (a long
        // narration would outlive the request timeout), so ok here means
        // "accepted" — ``isSpeaking`` doesn't track Kokoro playback yet.
        // Wiring a spoken-done frame for the indicator is a follow-up.
        // Pass the Kokoro pack matching the operator's voice_profile. Sent
        // per-utterance because during first boot no character is bound
        // yet, so the Python side has nothing to resolve a voice from.
        var args: [String: any Sendable] = ["text": body]
        if let pack = VoiceStageResolver.kokoroVoice(for: voiceStage,
                                                     profile: preferredVoiceProfile) {
            args["voice"] = pack
        }
        let result = await bridge.command("speak", args: args)
        if !result.ok {
            NSLog("[TTSManager] bridge speak refused (\(result.error ?? "?")) — falling back to Apple synth")
        }
        return result.ok
    }

    /// Local synthesis via the Apple backend — the "apple" engine and the
    /// no-bridge fallback.
    private func speakLocally(_ body: String) {
        log.info("speak via \(self.appleSpeech.displayName, privacy: .public) — \(body.count) chars")
        isSpeaking = true
        appleSpeech.speak(text: body) { [weak self] _ in
            // Backend already hops to main before firing — we mirror
            // its isSpeaking transition into ours.  Same pattern
            // STTManager uses; MainActor.assumeIsolated is the
            // ergonomic way to tell the compiler about the main-
            // queue contract the backend documented.
            MainActor.assumeIsolated {
                self?.isSpeaking = false
            }
        }
    }

    func stop() {
        activeBackend.stop()
        isSpeaking = false
    }
}
