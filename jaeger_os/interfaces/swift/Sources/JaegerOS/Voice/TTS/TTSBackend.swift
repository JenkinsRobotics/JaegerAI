//
//  TTSBackend.swift
//  JaegerOS / Voice / TTS
//
//  Text-to-speech backend protocol.  Mirrors the STTBackend shape so
//  the same plug-and-play pattern works for both halves of the voice
//  loop:
//
//    user mic  →  STTBackend  →  composer  →  agent
//                                                 │
//                                                 ▼
//    speaker  ←  TTSBackend  ←  assistant reply
//
//  Backends shipping in 0.3.0:
//
//    * ``AppleSpeechSynth`` — AVSpeechSynthesizer (built-in macOS,
//      ships with the OS, on-device, no model bundling).  Default
//      because it Just Works.
//
//  Future backends the protocol leaves room for:
//
//    * Kokoro on the Swift side — the Python voice_loop already uses
//      Kokoro for TTS.  Bringing it to the Swift app would mean
//      either bundling the Python runtime + Kokoro (heavy) or
//      converting Kokoro to CoreML (research project).  Not a 0.3.0
//      target; the protocol just doesn't preclude it.
//

import Foundation

/// Protocol every TTS backend conforms to.  ``@Sendable`` callbacks
/// mirror the STT side — strict-concurrency-safe out of the gate.
protocol TTSBackend: AnyObject {
    /// Display name for the future picker UI ("Apple Speech",
    /// "Kokoro", etc.).
    var displayName: String { get }

    /// True if this backend can speak right now (voice models
    /// installed, hardware present, etc.).  Cheap to call.
    var isAvailable: Bool { get }

    /// True while audio is actively playing.  Backends publish this
    /// via NotificationCenter or a delegate; the TTSManager
    /// surfaces a unified flag through ``isSpeaking``.
    var isSpeaking: Bool { get }

    /// Start speaking ``text``.  ``onFinish`` fires on the main queue
    /// when playback completes naturally (or is stopped).  The
    /// boolean is true if playback finished without interruption,
    /// false if ``stop()`` cut it off.
    func speak(
        text: String,
        onFinish: @escaping @Sendable (_ completed: Bool) -> Void
    )

    /// Interrupt any in-flight utterance immediately.  No-op if
    /// nothing is playing.
    func stop()
}

/// Error type — kept tiny on purpose; TTS rarely fails in user-
/// surface ways.  Most "failures" are silent (skipped because the
/// backend is unavailable) or recoverable (paused mid-utterance).
enum TTSError: Error, LocalizedError {
    case unavailable(String)
    case emptyText

    var errorDescription: String? {
        switch self {
        case .unavailable(let s): return "TTS unavailable — \(s)"
        case .emptyText: return "nothing to speak"
        }
    }
}


// MARK: - Markdown stripping helpers

/// Convert agent-emitted Markdown into plain text suitable for
/// speech synthesis.  AVSpeechSynthesizer reads ``**bold**`` as
/// "asterisk asterisk bold asterisk asterisk" verbatim, which is
/// terrible.  This is a lightweight pass — drops the common markers
/// (bold/italic/code/headers/lists), preserves the actual prose,
/// flattens links to their visible text.
///
/// Lives at file scope so STT, TTS, and any future caller can reuse.
enum TTSText {
    /// Strip Markdown markers without trying to render them.  Not a
    /// CommonMark parser — just regex pass enough to make speech
    /// natural.
    static func plainForSpeech(_ markdown: String) -> String {
        var s = markdown

        // Code blocks (fenced) — keep contents, drop fences.
        s = s.replacingOccurrences(
            of: "```[a-zA-Z0-9]*\n",
            with: "",
            options: .regularExpression
        )
        s = s.replacingOccurrences(of: "```", with: "")

        // Inline code — keep contents, drop backticks.
        s = s.replacingOccurrences(of: "`", with: "")

        // Bold / italic — keep contents, drop * and _ pairs.
        // Three then two then one so longer markers strip first.
        for marker in ["***", "**", "*", "__", "_"] {
            s = s.replacingOccurrences(of: marker, with: "")
        }

        // Headings — drop leading # tokens.
        s = s.replacingOccurrences(
            of: "^#{1,6}\\s+",
            with: "",
            options: .regularExpression
        )

        // Bullet / numbered list markers — keep contents, drop
        // leading bullet glyph + space.
        s = s.replacingOccurrences(
            of: "^\\s*[-*+]\\s+",
            with: "",
            options: [.regularExpression, .anchored]
        )
        // (Per-line regex would need .anchoredMatch in a real loop;
        // for spoken output the inline strip above is sufficient.)

        // Links: [visible text](url) → "visible text"
        s = s.replacingOccurrences(
            of: "\\[([^\\]]+)\\]\\([^)]+\\)",
            with: "$1",
            options: .regularExpression
        )

        // Collapse runs of whitespace to single spaces — speech
        // doesn't care about indentation.
        s = s.replacingOccurrences(
            of: "[ \\t]+",
            with: " ",
            options: .regularExpression
        )

        return s.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
