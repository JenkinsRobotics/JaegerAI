// VoiceController.swift — S4 glue between the `jaeger` bridge and the ported voice pieces (Jaeger original).
// Events: voice.state {state}, voice.level {rms}, voice.transcript {text, final, confidence}, voice.error {message},
// tts.done {completed}. Permission prompts happen only from a real mic.start (mic) and the first real
// transcription (speech recognition); status() only reads authorisation states.
import AVFoundation
import Foundation
import JaegerShellCore
import Speech

typealias BridgeDone = (_ result: [String: Any]?, _ error: String?) -> Void

final class VoiceController {
    private let emit: ([String: Any]) -> Void
    private lazy var recorder = VoiceRecorder()
    private let stt = AppleSpeechSTT()
    let tts = AppleSpeechSynth()
    private var levelTimer: Timer?
    private(set) var state = "idle"

    init(emit: @escaping ([String: Any]) -> Void) { self.emit = emit }

    private func setState(_ value: String) {
        state = value
        emit(["type": "voice.state", "state": value])
    }

    static func micPermission() -> String {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: return "authorized"
        case .denied: return "denied"
        case .restricted: return "restricted"
        case .notDetermined: return "not_determined"
        @unknown default: return "unknown"
        }
    }

    static func speechPermission() -> String {
        switch SFSpeechRecognizer.authorizationStatus() {
        case .authorized: return "authorized"
        case .denied: return "denied"
        case .restricted: return "restricted"
        case .notDetermined: return "not_determined"
        @unknown default: return "unknown"
        }
    }

    static func installedVoices() -> Set<String> { Set(AVSpeechSynthesisVoice.speechVoices().map(\.identifier)) }

    /// Read-only; never prompts.
    static func status(state: String, speaking: Bool) -> [String: Any] {
        let recognizer = SFSpeechRecognizer()
        return [
            "mic_permission": micPermission(),
            "speech_permission": speechPermission(),
            "has_audio_input": VoiceRecorder.hasAudioInput,
            "recognizer_available": recognizer?.isAvailable ?? false,
            "on_device_recognition": recognizer?.supportsOnDeviceRecognition ?? false,
            "voices_installed": installedVoices().count,
            "state": state,
            "speaking": speaking,
        ]
    }

    func micStart(mode: String, done: @escaping BridgeDone) {
        if recorder.isRecording { done(["listening": true, "mode": mode], nil); return }
        tts.stop()
        VoiceRecorder.requestMicrophoneAccess { [weak self] granted in
            DispatchQueue.main.async {
                guard let self else { return }
                guard granted else {
                    self.emit(["type": "voice.error", "message": "microphone permission denied"])
                    done(nil, "mic_permission_denied")
                    return
                }
                do {
                    try self.recorder.startRecording()
                    self.setState("listening")
                    self.levelTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
                        guard let self else { return }
                        self.emit(["type": "voice.level", "rms": Double(self.recorder.level)])
                    }
                    done(["listening": true, "mode": mode], nil)
                } catch {
                    done(nil, "mic_start_failed: \(error.localizedDescription)")
                }
            }
        }
    }

    func micStop(done: @escaping BridgeDone) {
        guard recorder.isRecording else { done(nil, "not_recording"); return }
        recorder.stopRecording()
        levelTimer?.invalidate()
        levelTimer = nil
        guard let audio = recorder.takeCapturedAudio() else {
            setState("idle")
            done(nil, "no_audio_captured")
            return
        }
        let seconds = Double(audio.samples.count) / max(audio.format.sampleRate, 1)
        setState("transcribing")
        done(["seconds": seconds], nil)
        stt.transcribe(samples: audio.samples, format: audio.format) { [weak self] result in
            DispatchQueue.main.async {
                switch result {
                case .success(let r):
                    self?.emit(["type": "voice.transcript", "text": r.text, "final": true,
                                "confidence": r.confidence.map { Double($0) } ?? NSNull()])
                case .failure(let error):
                    self?.emit(["type": "voice.error", "message": error.localizedDescription])
                }
                self?.setState("idle")
            }
        }
    }

    func speak(text: String, voice: String?, done: @escaping BridgeDone) {
        let body = TTSText.plainForSpeech(text)
        guard !body.isEmpty else { done(nil, "nothing_to_speak"); return }
        guard !recorder.isRecording else { done(nil, "busy_listening"); return }
        tts.voiceIdentifier = VoiceCatalog.resolve(voice, installed: Self.installedVoices())
        setState("speaking")
        tts.speak(text: body) { [weak self] completed in
            self?.emit(["type": "tts.done", "completed": completed])
            self?.setState("idle")
        }
        done(["speaking": true, "chars": body.count, "voice": tts.resolvedVoice()?.identifier ?? "system_default"], nil)
    }

    func stopSpeaking() { tts.stop() }

    func shutdown() {
        levelTimer?.invalidate()
        if recorder.isRecording { recorder.stopRecording() }
        tts.stop()
    }
}
