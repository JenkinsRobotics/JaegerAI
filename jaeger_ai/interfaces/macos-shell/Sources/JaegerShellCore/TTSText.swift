// JaegerShellCore: Markdown → speakable text.
// Ported from jaeger_ai/interfaces/swift/Sources/JaegerAI/Voice/TTS/TTSBackend.swift:87-155 (`TTSText`,
// Jenkins Robotics); behaviour unchanged, made public.
import Foundation

public enum TTSText {
    public static func plainForSpeech(_ markdown: String) -> String {
        var s = markdown
        s = s.replacingOccurrences(of: "```[a-zA-Z0-9]*\n", with: "", options: .regularExpression)
        s = s.replacingOccurrences(of: "```", with: "")
        s = s.replacingOccurrences(of: "`", with: "")
        for marker in ["***", "**", "*", "__", "_"] {
            s = s.replacingOccurrences(of: marker, with: "")
        }
        s = s.replacingOccurrences(of: "^#{1,6}\\s+", with: "", options: .regularExpression)
        s = s.replacingOccurrences(of: "^\\s*[-*+]\\s+", with: "", options: [.regularExpression, .anchored])
        s = s.replacingOccurrences(of: "\\[([^\\]]+)\\]\\([^)]+\\)", with: "$1", options: .regularExpression)
        s = s.replacingOccurrences(of: "[ \\t]+", with: " ", options: .regularExpression)
        s = s.replacingOccurrences(of: "([.!?])\\s+", with: "$1  ", options: .regularExpression)
        return s.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
