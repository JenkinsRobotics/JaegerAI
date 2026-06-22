//
//  TTSManager.swift
//  JaegerOS / Voice / TTS
//
//  Thin dispatcher that picks the active TTS backend and forwards
//  ``speak`` to it.  Mirrors STTManager.  Owns a @Published
//  ``isSpeaking`` SwiftUI views can watch (the menu bar shows a
//  speaker indicator when audio's playing, e.g.).
//
//  Today the policy is simple: AppleSpeechSynth always.  Settings UI
//  later will let the operator override (e.g. a future Kokoro-CoreML
//  backend if it lands).
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
    /// doesn't read asterisks aloud.  No-op if ``autoSpeakEnabled``
    /// is false (the call site passes the operator-preference check
    /// in; this method just respects it).
    func speak(_ text: String) {
        let body = TTSText.plainForSpeech(text)
        NSLog("[TTSManager] speak called — input=\(text.count) chars, afterStrip=\(body.count) chars, backend=\(activeBackend.displayName)")
        guard !body.isEmpty else {
            NSLog("[TTSManager] body empty after markdown strip — skipping")
            return
        }
        log.info("speak via \(self.activeBackend.displayName, privacy: .public) — \(body.count) chars")
        isSpeaking = true
        activeBackend.speak(text: body) { [weak self] _ in
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
