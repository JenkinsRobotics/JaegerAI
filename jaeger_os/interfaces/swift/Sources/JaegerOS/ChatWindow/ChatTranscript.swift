//
//  ChatTranscript.swift
//  JaegerOS / ChatWindow
//
//  The transcript's row views + small chrome, split out of ChatView so the
//  surface file stays the layout and this file stays the typography:
//
//    * ``JaegerBanner``  — the ASCII art heading an empty transcript
//    * ``TranscriptRow`` — one turn/chip in the terminal aesthetic
//    * ``LevelBar``      — the mic level meter under the composer
//    * ``ThinkingDots``  — the waiting indicator (TimelineView-driven,
//                          no unstructured task loops; it only exists
//                          while a reply is pending, so idle cost is zero)
//

import SwiftUI

// MARK: - Banner

/// The JAEGER ASCII banner — same art the terminal TUI prints at boot
/// (``interfaces/tui/banner.py``).  Sized small enough that all 70
/// columns fit the chat window's min width.
struct JaegerBanner: View {
    private static let art = """
     ██╗ █████╗ ███████╗ ██████╗ ███████╗██████╗       ██████╗ ███████╗
     ██║██╔══██╗██╔════╝██╔════╝ ██╔════╝██╔══██╗     ██╔═══██╗██╔════╝
     ██║███████║█████╗  ██║  ███╗█████╗  ██████╔╝     ██║   ██║███████╗
██   ██║██╔══██║██╔══╝  ██║   ██║██╔══╝  ██╔══██╗     ██║   ██║╚════██║
╚█████╔╝██║  ██║███████╗╚██████╔╝███████╗██║  ██║ ██╗ ╚██████╔╝███████║
 ╚════╝ ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝ ╚═╝  ╚═════╝ ╚══════╝
"""

    var body: some View {
        VStack(spacing: 8) {
            Text(Self.art)
                .font(.system(size: 8, design: .monospaced))
                .foregroundColor(Term.accent)
                .fixedSize()
                .minimumScaleFactor(0.4)
                .lineLimit(6)
            Text("✦  real-world local agentic agent framework  ✦")
                .font(.system(size: 11, design: .monospaced))
                .foregroundColor(Term.accent.opacity(0.6))
        }
    }
}

// MARK: - TranscriptRow

/// One transcript line in the terminal aesthetic.  Roles are left-aligned
/// and prefixed (``❯`` for you, the agent name for replies) rather than
/// bubbled — the windowed echo of the Rich terminal TUI's turn log.
struct TranscriptRow: View {
    let message: ChatMessage
    /// Draw the thin accent rule ABOVE this row — the turn separator the
    /// view puts before every user message after the first (config-gated
    /// by ``display.turn_separators``).
    var showTurnRule: Bool = false

    var body: some View {
        switch message.author {
        case .user:      userRow
        case .assistant: assistantRow
        case .system:    systemRow
        case .thinking:  thinkingRow
        case .toolCall:  toolRow
        }
    }

    private var userRow: some View {
        VStack(alignment: .leading, spacing: 10) {
            if showTurnRule {
                Rectangle()
                    .fill(Term.rule)
                    .frame(height: 1)
                    .padding(.vertical, 2)
            }
            HStack(alignment: .top, spacing: 8) {
                Text("❯")
                    .font(Term.mono.weight(.bold))
                    .foregroundColor(Term.accent)
                Text(message.text)
                    .font(Term.mono)
                    .foregroundColor(Term.ink)
                    .textSelection(.enabled)
                Spacer(minLength: 0)
            }
        }
    }

    private var assistantRow: some View {
        VStack(alignment: .leading, spacing: 3) {
            if message.text.isEmpty && message.isStreaming {
                ThinkingDots()
            } else {
                // Markdown so **bold**, *italics*, `code` land formatted;
                // permissive parser falls back to plain on malformed input.
                markdownText
                    .font(Term.mono)
                    .foregroundColor(Term.ink)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)

                // Telemetry trail — the TUI's "replied in 3s" line, dimmed
                // under the reply. Only exists when the core sent it.
                if let meta = message.meta {
                    Text(meta)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundColor(Term.inkDim.opacity(0.8))
                }

                // Manual "speak this" — finished rows only.  The agent's
                // own Kokoro tool stays the primary TTS path.
                if !message.text.isEmpty {
                    Button(action: { TTSManager.shared.speak(message.text) }) {
                        Image(systemName: "speaker.wave.2")
                            .font(.system(size: 11))
                            .foregroundColor(Term.inkDim)
                    }
                    .buttonStyle(.plain)
                    .help("Speak this reply")
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private var markdownText: some View {
        if let attr = try? AttributedString(
            markdown: message.text,
            options: AttributedString.MarkdownParsingOptions(
                interpretedSyntax: .inlineOnlyPreservingWhitespace
            )
        ) {
            Text(attr)
        } else {
            Text(message.text)
        }
    }

    private var systemRow: some View {
        Text(message.text)
            .font(.system(size: 12, design: .monospaced))
            .foregroundColor(Term.inkDim)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// Reasoning trail — dim italic mono, a leading ``…`` marker.
    /// Indented under the turn's ``❯`` line (operator keeper, 2026-07-05).
    private var thinkingRow: some View {
        HStack(alignment: .top, spacing: 6) {
            Image(systemName: "brain")
                .font(.system(size: 11))
                .foregroundColor(Term.inkDim)
            Text(message.text)
                .font(.system(size: 12, design: .monospaced))
                .italic()
                .foregroundColor(Term.inkDim)
            if message.isStreaming { ThinkingDots() }
            Spacer(minLength: 0)
        }
        .padding(.leading, 18)
    }

    /// Tool-call line — accent-tinted mono with a ``⏵`` marker, the
    /// windowed echo of the TUI's live tool-progress print.
    private var toolRow: some View {
        HStack(spacing: 6) {
            Text("⏵")
                .font(.system(size: 12, design: .monospaced))
                .foregroundColor(Term.accent)
            Text(message.text)
                .font(.system(size: 12, design: .monospaced))
                .foregroundColor(Term.accent.opacity(0.9))
            if message.isStreaming {
                ProgressView().controlSize(.mini)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 4)
        .background(
            RoundedRectangle(cornerRadius: 6)
                .fill(Term.accent.opacity(0.08))
        )
        // Indent under the turn's ``❯`` line so the trace reads as
        // nested activity, not sibling messages (operator keeper).
        .padding(.leading, 18)
    }
}

// MARK: - LevelBar

/// Thin one-pixel bar showing the mic's current peak level — sits
/// at the bottom of the composer field while recording.  Cheap and
/// readable; doesn't compete with the chat content.
struct LevelBar: View {
    let level: Float

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule()
                    .fill(Color.red.opacity(0.15))
                Capsule()
                    .fill(Color.red.opacity(0.75))
                    .frame(width: geo.size.width * CGFloat(level))
                    .animation(.linear(duration: 0.05), value: level)
            }
        }
    }
}

// MARK: - ThinkingDots

/// Three pulsing dots while we wait for the agent's reply.  Driven by a
/// TimelineView schedule — no unstructured ``while`` task loop — and the
/// view only exists while a reply is pending, so there is nothing ticking
/// when the app is idle.
struct ThinkingDots: View {
    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.35)) { tl in
            let phase = Int(tl.date.timeIntervalSinceReferenceDate / 0.35) % 3
            HStack(spacing: 4) {
                ForEach(0..<3, id: \.self) { i in
                    Circle()
                        .fill(Term.accent)
                        .frame(width: 6, height: 6)
                        .opacity(phase == i ? 1.0 : 0.3)
                }
            }
        }
    }
}
