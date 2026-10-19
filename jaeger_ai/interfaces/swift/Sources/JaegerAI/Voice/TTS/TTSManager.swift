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

    /// Owned speech is queued or awaiting settlement; not a microphone/audio-device measurement.
    @Published private(set) var isSpeaking: Bool = false
    @Published private(set) var measuredAmplitude: Double = 0
    @Published private(set) var playbackUnknown = false
    @Published private(set) var systemSpeechActive = false
    private var telemetryTask: Task<Void, Never>?
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
    /// Cancels old demand before enqueueing the new stage. The shared drain
    /// waits for the old request to settle and the Stop dispatch to return.
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

    // One drain owns every utterance, including speakAndWait. An epoch
    // invalidates cancelled work; late acknowledgements cannot alter a new run.
    private struct Utterance {
        let body: String
        let rate: Float?
        let epoch: UInt64
        let completion: CheckedContinuation<Bool, Never>?
    }
    private var pending: [Utterance] = []
    private var epoch: UInt64 = 0
    private var draining = false
    private var stopBarrier: Task<Void, Never>?

    // Test seams avoid microphones, synthesizers and live bridge traffic.
    enum SpeechResult { case spoken, failed(String) }
    private let speechOverride: (@MainActor (String, Float?) async -> SpeechResult)?
    private let stopOverride: (@MainActor () async -> Void)?

    init(
        speech: (@MainActor (String, Float?) async -> SpeechResult)? = nil,
        stopSpeech: (@MainActor () async -> Void)? = nil
    ) {
        speechOverride = speech
        stopOverride = stopSpeech
    }

    /// Enqueue explicit speech. Auto-speak preference belongs to the caller.
    func speak(_ text: String) {
        let body = TTSText.plainForSpeech(text)
        guard !body.isEmpty else { return }
        enqueue(body, rate: nil, completion: nil)
    }

    private func enqueue(
        _ body: String, rate: Float?, completion: CheckedContinuation<Bool, Never>?
    ) {
        pending.append(Utterance(body: body, rate: rate, epoch: epoch, completion: completion))
        isSpeaking = true
        guard !draining else { return }
        draining = true
        if speechOverride == nil {
            telemetryTask = Task { @MainActor [weak self] in
                while let self, self.draining, !Task.isCancelled {
                    let result = await AgentBridge.shared.query("speech_status")
                    if Task.isCancelled { break }
                    let object = result.json.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
                    self.measuredAmplitude = (object?["measured"] as? Bool == true) ? min(1, max(0, object?["amplitude"] as? Double ?? 0)) : 0
                    self.playbackUnknown = object?["execution_unknown"] as? Bool ?? false
                    try? await Task.sleep(for: .milliseconds(70))
                }
            }
        }
        Task { @MainActor in await drain() }
    }

    private func drain() async {
        while !pending.isEmpty {
            let item = pending.removeFirst()
            // A delayed Stop must finish dispatch before a newer utterance.
            await stopBarrier?.value
            guard item.epoch == epoch else {
                item.completion?.resume(returning: false)
                continue
            }
            lastError = nil
            let result: SpeechResult
            if let speechOverride {
                result = await speechOverride(item.body, item.rate)
            } else {
                result = await performSpeech(item.body, rate: item.rate, epoch: item.epoch)
            }
            let current = item.epoch == epoch
            var completed = false
            if current {
                switch result {
                case .spoken: completed = true
                case .failed(let reason): lastError = reason
                }
            }
            item.completion?.resume(returning: completed)
        }
        draining = false
        telemetryTask?.cancel(); telemetryTask = nil
        measuredAmplitude = 0
        isSpeaking = false
    }

    private enum FrameworkResult {
        case spoken
        case useApple(String)
        case failed(String)
    }

    /// Route interface speech through JaegerOS's TTS slot and await SpokenAck.
    /// A failed/timed-out request cannot certify physical playback termination.
    private func speakViaFramework(
        _ body: String,
        rate overrideRate: Float? = nil,
        epoch expectedEpoch: UInt64
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
        guard expectedEpoch == epoch else { return .failed("Speech cancelled before submission.") }
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

    /// Await this queued utterance, not merely its submission to the bridge.
    func speakAndWait(_ text: String, rate: Float? = nil) async -> Bool {
        let body = TTSText.plainForSpeech(text)
        guard !body.isEmpty else { return false }
        return await withCheckedContinuation { completion in
            enqueue(body, rate: rate, completion: completion)
        }
    }

    private func performSpeech(_ body: String, rate: Float?, epoch: UInt64) async -> SpeechResult {
        switch await speakViaFramework(body, rate: rate, epoch: epoch) {
        case .spoken: return .spoken
        case .failed(let reason): return .failed(reason)
        case .useApple:
            guard epoch == self.epoch else { return .failed("Speech cancelled before submission.") }
            systemSpeechActive = true
            let completed = await withCheckedContinuation { continuation in
                appleSpeech.speak(text: body) { completed in
                    continuation.resume(returning: completed)
                }
            }
            systemSpeechActive = false
            return completed ? .spoken : .failed("System speech did not complete playback.")
        }
    }

    /// Cancel queued demand immediately. Keep active ownership until its
    /// completion/timeout; requesting Stop does not confirm device silence.
    func stop() {
        measuredAmplitude = 0
        systemSpeechActive = false
        epoch &+= 1
        for item in pending { item.completion?.resume(returning: false) }
        pending.removeAll()
        appleSpeech.stop()
        let previous = stopBarrier
        stopBarrier = Task { @MainActor in
            await previous?.value
            if let stopOverride {
                await stopOverride()
            } else if AgentBridge.shared.isConnected {
                _ = await AgentBridge.shared.command("stop_speech")
            }
        }
        if !draining { isSpeaking = false }
    }
}
