//
//  TTSManager.swift
//  JaegerAI / Voice / TTS
//
//  Thin dispatcher that picks the active TTS backend and forwards
//  ``speak`` to it.  Mirrors STTManager.  Owns a @Published
//  ``isSpeaking`` SwiftUI views can watch (the menu bar shows a
//  speaker indicator when audio's playing, e.g.).
//
//  Engine routing: UI-owned speech publishes through JaegerOS's TTS slot;
//  Kokoro is the installed neural module today. Installer narration uses a
//  fixed technical pack and never silently degrades to Apple speech. Normal
//  operation still honors an explicit `speech_engine: apple` preference and
//  exposes any emergency fallback reason through `lastError`.
//

import Foundation
import os

@MainActor
final class TTSManager: ObservableObject {
    static let shared = TTSManager()

    @Published private(set) var isSpeaking: Bool = false
    @Published private(set) var lastError: String?

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
    /// ``.installer`` for OS 1 setup (technical Kokoro voice, ignores
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
        stop()
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
            self.lastError = nil
            self.isSpeaking = true
            switch await self.speakViaFramework(body) {
            case .spoken:
                self.isSpeaking = false
            case .useApple(let reason):
                self.lastError = reason
                self.speakLocally(body)
            case .failed(let reason):
                self.lastError = reason
                self.isSpeaking = false
            }
        }
    }

    private enum FrameworkResult {
        case spoken
        case useApple(String)
        case failed(String)
    }

    /// Route interface speech through JaegerOS's TTS slot. The bridge waits
    /// for the real SpokenAck, so `isSpeaking` and the setup handoff describe
    /// playback rather than merely saying that a background thread started.
    private func speakViaFramework(
        _ body: String,
        rate overrideRate: Float? = nil
    ) async -> FrameworkResult {
        let bridge = AgentBridge.shared
        guard bridge.isConnected else {
            let reason = "Neural voice unavailable because the agent bridge is disconnected."
            return .failed(reason)
        }
        // The engine choice lives in config.yaml (voice.speech_engine,
        // default "kokoro") and is read over the EXISTING config query on
        // every utterance — a config edit applies on the next speak, no
        // restart.  An unreadable config defaults to kokoro: the bridge is
        // up, so prefer the agent's real voice.
        let cfg = await bridge.query("config")
        if cfg.ok, let json = cfg.json,
           let obj = (try? JSONSerialization.jsonObject(with: json)) as? [String: Any],
           let engine = obj["speech_engine"] as? String,
           voiceStage == .persona,
           engine == "apple" {
            return .useApple("System speech is selected in voice settings.")
        }
        log.info("speak via JaegerOS tts slot — \(body.count) chars")
        // Pass the Kokoro pack matching the operator's voice_profile. Sent
        // per-utterance because during first boot no character is bound
        // yet, so the Python side has nothing to resolve a voice from.
        var args: [String: any Sendable] = ["text": body]
        if let pack = VoiceStageResolver.kokoroVoice(for: voiceStage,
                                                     profile: preferredVoiceProfile) {
            args["voice"] = pack
        }
        args["rate"] = Double(
            overrideRate ?? VoiceStageResolver.kokoroRate(for: voiceStage)
        )
        args["wait"] = true
        let result = await bridge.command(
            "speak", args: args, timeout: .seconds(190))
        if !result.ok {
            let reason = result.error ?? "The configured neural voice did not complete playback."
            NSLog("[TTSManager] JaegerOS speech failed: \(reason)")
            return .failed(reason)
        }
        return .spoken
    }

    /// Speak one complete utterance before returning. Used at the setup →
    /// agent handoff so the Kokoro voice pack never changes mid-sentence.
    func speakAndWait(_ text: String, rate: Float? = nil) async -> Bool {
        let body = TTSText.plainForSpeech(text)
        guard !body.isEmpty else { return false }
        lastError = nil
        isSpeaking = true
        switch await speakViaFramework(body, rate: rate) {
        case .spoken:
            isSpeaking = false
            return true
        case .failed(let reason):
            lastError = reason
            isSpeaking = false
            return false
        case .useApple(let reason):
            lastError = reason
            let completed = await withCheckedContinuation { continuation in
                appleSpeech.speak(text: body) { completed in
                    continuation.resume(returning: completed)
                }
            }
            isSpeaking = false
            return completed
        }
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
        appleSpeech.stop()
        isSpeaking = false
        guard AgentBridge.shared.isConnected else { return }
        Task {
            _ = await AgentBridge.shared.command("stop_speech")
        }
    }
}
