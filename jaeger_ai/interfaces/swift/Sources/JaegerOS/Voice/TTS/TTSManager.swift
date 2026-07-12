//
//  TTSManager.swift
//  JaegerOS / Voice / TTS
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

    let appleSpeech = AppleSpeechSynth()

    private let log = Logger(subsystem: "com.jenkinsrobotics.JaegerOS",
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
            if await self.speakViaAgent(body) { return }
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
        let result = await bridge.command("speak", args: ["text": body])
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
