// AppleSpeechSynth.swift — adapted from jaeger_ai/interfaces/swift/Sources/JaegerAI/Voice/TTS/AppleSpeechSynth.swift:32-196
// (Jenkins Robotics). Changes: no VoiceStage (voice chosen via JaegerShellCore.VoiceCatalog); shell log tags;
// added render() — silent synthesis through AVSpeechSynthesizer.write (nothing is played) for headless checks.
import AVFoundation
import Foundation

final class AppleSpeechSynth: NSObject, AVSpeechSynthesizerDelegate {
    var voiceIdentifier: String?
    var rate: Float = AVSpeechUtteranceDefaultSpeechRate
    private(set) var isSpeaking = false
    private let synth = AVSpeechSynthesizer()
    private let renderSynth = AVSpeechSynthesizer()
    private var currentFinish: ((Bool) -> Void)?

    override init() {
        super.init()
        synth.delegate = self
    }

    func resolvedVoice() -> AVSpeechSynthesisVoice? {
        if let id = voiceIdentifier, let v = AVSpeechSynthesisVoice(identifier: id) { return v }
        if let v = AVSpeechSynthesisVoice(language: Locale.current.identifier) { return v }
        if let v = AVSpeechSynthesisVoice(language: "en-US") { return v }
        return AVSpeechSynthesisVoice(identifier: "com.apple.voice.compact.en-US.Samantha")
    }

    func speak(text: String, onFinish: @escaping (_ completed: Bool) -> Void) {
        let body = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !body.isEmpty else { DispatchQueue.main.async { onFinish(true) }; return }
        if synth.isSpeaking { synth.stopSpeaking(at: .immediate) }
        currentFinish?(false)
        let utterance = AVSpeechUtterance(string: body)
        utterance.rate = rate
        utterance.voice = resolvedVoice()
        utterance.volume = 1.0
        currentFinish = onFinish
        isSpeaking = true
        synth.speak(utterance)
        shellLog("[shell][tts] speaking \(body.count) chars, voice \(utterance.voice?.identifier ?? "nil")")
    }

    func stop() {
        guard synth.isSpeaking else { return }
        synth.stopSpeaking(at: .immediate)
    }

    /// Silent synthesis: counts rendered PCM frames; nothing reaches the speakers.
    func render(text: String, done: @escaping (_ frames: Int, _ sampleRate: Double, _ voice: String?) -> Void) {
        let utterance = AVSpeechUtterance(string: text)
        utterance.rate = rate
        utterance.voice = resolvedVoice()
        var frames = 0
        var sampleRate = 0.0
        var reported = false
        let report = {
            guard !reported else { return }
            reported = true
            done(frames, sampleRate, utterance.voice?.identifier)
        }
        renderSynth.write(utterance) { buffer in
            guard let pcm = buffer as? AVAudioPCMBuffer else { return }
            let n = Int(pcm.frameLength)
            let rate = pcm.format.sampleRate
            DispatchQueue.main.async {
                if n == 0 { report() } else { frames += n; sampleRate = rate }
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 8) { report() }
    }

    func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) { finalize(true) }
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) { finalize(false) }

    private func finalize(_ completed: Bool) {
        let callback = currentFinish
        currentFinish = nil
        DispatchQueue.main.async { [weak self] in
            self?.isSpeaking = false
            callback?(completed)
        }
    }
}
