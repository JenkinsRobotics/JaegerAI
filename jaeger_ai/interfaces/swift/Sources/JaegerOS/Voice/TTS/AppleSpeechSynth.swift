//
//  AppleSpeechSynth.swift
//  JaegerOS / Voice / TTS
//
//  AVSpeechSynthesizer backend — Apple's built-in text-to-speech.
//  Default TTS for v1 because:
//
//    * Ships with macOS — no model bundling
//    * Free, no API key, runs locally
//    * Good range of voices (the operator can pick one in System
//      Settings → Accessibility → Spoken Content; we honour that)
//    * Apple Silicon has a neural voice engine for the high-quality
//      voices ("Ava (Premium)", "Evan (Premium)", etc.); they sound
//      meaningfully better than the older voices
//
//  Limitations vs. a future Kokoro/CoreML backend:
//
//    * Voice character is what Apple ships; no custom voices
//    * No fine prosody control beyond rate / pitch / volume
//    * Latency is good but not great (~50-200ms to start speaking)
//
//  AVSpeechSynthesizer delegate methods need a non-MainActor object
//  (the framework calls them from its own queue), so this class is
//  NOT @MainActor.  Same pattern VoiceRecorder uses — @unchecked
//  Sendable, UI flag updates dispatch to main explicitly.
//

import AVFoundation
import Foundation
import os

final class AppleSpeechSynth: NSObject, TTSBackend, AVSpeechSynthesizerDelegate,
                              @unchecked Sendable {
    let displayName: String = "Apple Speech (system voice)"

    var isAvailable: Bool {
        // Available on every macOS 14+ install — only false if the
        // synthesizer somehow fails to init, which doesn't happen
        // in practice.
        return true
    }

    private(set) var isSpeaking: Bool = false

    /// Optional voice identifier override.  Nil = use the system
    /// default voice (which the operator picks in System Settings →
    /// Accessibility → Spoken Content → System Voice).  Settable
    /// later when we wire a picker UI.
    var voiceIdentifier: String? = nil

    /// Speech rate — 0.0 (slow) to 1.0 (fast).  Default ~0.5 sounds
    /// natural for chat replies; closer to ``AVSpeechUtteranceDefaultSpeechRate``.
    var rate: Float = AVSpeechUtteranceDefaultSpeechRate

    private let synth = AVSpeechSynthesizer()
    private let log = Logger(subsystem: "com.jenkinsrobotics.JaegerOS",
                             category: "AppleSpeechSynth")

    /// Callback for the current utterance, if any.  Cleared after
    /// each finish / cancel so a late delegate callback from a
    /// previous utterance doesn't fire a callback meant for the
    /// next one.
    private var currentFinish: (@Sendable (Bool) -> Void)?

    override init() {
        super.init()
        synth.delegate = self
    }

    // MARK: - TTSBackend

    func speak(
        text: String,
        onFinish: @escaping @Sendable (_ completed: Bool) -> Void
    ) {
        let body = text.trimmingCharacters(in: .whitespacesAndNewlines)
        NSLog("[AppleSpeechSynth] speak called, body=\(body.count) chars, alreadySpeaking=\(synth.isSpeaking)")
        guard !body.isEmpty else {
            DispatchQueue.main.async { onFinish(true) }
            return
        }

        // Interrupt anything currently speaking before queueing the
        // new utterance.  We could also use ``.add(_:)`` to chain,
        // but for chat replies the operator almost certainly wants
        // the NEW reply, not the tail end of an older one.
        if synth.isSpeaking {
            synth.stopSpeaking(at: .immediate)
        }
        // Replace the prior callback — it'll never fire now.
        currentFinish?(false)

        let utterance = AVSpeechUtterance(string: body)
        utterance.rate = rate
        // ALWAYS set utterance.voice explicitly.  There's a known
        // macOS 26 / Swift 6 quirk where nil-voice utterances get
        // queued by ``synth.speak`` (no error) but never actually
        // start playback — ``didStart`` never fires, audio is
        // silent.  Setting a concrete voice avoids the no-op path.
        let resolvedVoice: AVSpeechSynthesisVoice? = {
            if let voiceId = voiceIdentifier,
               let v = AVSpeechSynthesisVoice(identifier: voiceId) {
                return v
            }
            // Fall back chain: current-locale voice → English →
            // hardcoded Samantha (always installed on every macOS).
            if let v = AVSpeechSynthesisVoice(
                language: Locale.current.identifier
            ) {
                return v
            }
            if let v = AVSpeechSynthesisVoice(language: "en-US") {
                return v
            }
            return AVSpeechSynthesisVoice(
                identifier: "com.apple.voice.compact.en-US.Samantha"
            )
        }()
        utterance.voice = resolvedVoice
        NSLog("[AppleSpeechSynth] voice resolved to \(resolvedVoice?.identifier ?? "<nil — will be silent>")")
        utterance.volume = 1.0  // explicit 1.0 (default but be explicit)

        currentFinish = onFinish
        DispatchQueue.main.async { [weak self] in
            self?.isSpeaking = true
        }
        synth.speak(utterance)
        NSLog("[AppleSpeechSynth] synth.speak(utterance) returned — playback should start")
        log.info("speaking \(body.count) chars")
    }

    func stop() {
        guard synth.isSpeaking else { return }
        synth.stopSpeaking(at: .immediate)
        // Delegate's didCancel will fire and run the finish callback
        // with completed=false.
    }

    // MARK: - AVSpeechSynthesizerDelegate
    //
    // These run on AVFoundation's internal queue.  We hop to main
    // before touching ``isSpeaking`` + firing the callback so SwiftUI
    // bindings + downstream code stay on the right thread.

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer,
                           didStart utterance: AVSpeechUtterance) {
        NSLog("[AppleSpeechSynth] didStart — audio should be playing")
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer,
                           didFinish utterance: AVSpeechUtterance) {
        NSLog("[AppleSpeechSynth] didFinish")
        finalize(completed: true)
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer,
                           didCancel utterance: AVSpeechUtterance) {
        NSLog("[AppleSpeechSynth] didCancel")
        finalize(completed: false)
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer,
                           didPause utterance: AVSpeechUtterance) {
        NSLog("[AppleSpeechSynth] didPause")
    }

    private func finalize(completed: Bool) {
        let cb = self.currentFinish
        self.currentFinish = nil
        DispatchQueue.main.async { [weak self] in
            self?.isSpeaking = false
            cb?(completed)
        }
    }
}
