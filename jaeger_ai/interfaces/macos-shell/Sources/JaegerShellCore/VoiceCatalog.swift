// JaegerShellCore: system-voice choice for `tts.speak {voice}`.
// Adapted from jaeger_ai/interfaces/swift/Sources/JaegerAI/Voice/TTS/VoiceStage.swift:57-75, 114-127, 149-152
// (persona tables + first-installed resolver, Jenkins Robotics). Installer stage and Kokoro tables not reused.
public enum VoiceCatalog {
    public static let personaVoices: [String: [String]] = [
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
            "com.apple.voice.compact.en-GB.Daniel",
        ],
    ]

    /// nil → system default. A persona name picks the first installed voice from its table;
    /// an exact installed identifier is used as-is; anything else → nil.
    public static func resolve(_ choice: String?, installed: Set<String>) -> String? {
        guard let choice, !choice.isEmpty else { return nil }
        if let candidates = personaVoices[choice.lowercased()] { return candidates.first { installed.contains($0) } }
        return installed.contains(choice) ? choice : nil
    }
}
