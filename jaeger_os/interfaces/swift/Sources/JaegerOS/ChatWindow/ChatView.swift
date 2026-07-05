//
//  ChatView.swift
//  JaegerOS / ChatWindow
//
//  Main chat surface — a windowed take on the JROS Rich **terminal**
//  TUI (``jaeger_os/interfaces/tui``), not an iMessage bubble sheet:
//
//    * Dark terminal canvas, monospaced throughout
//    * Brand accent ``#3aa0ff`` (the TUI's ``theme.ACCENT``) on the
//      banner, the ``❯`` prompt, turn rules, and tool chips
//    * Turns read as a transcript: ``❯ <you>`` then the agent's reply
//      as a flowing mono block, separated by thin accent rules — no
//      left/right bubbles
//    * JAEGER ASCII banner heads an empty transcript (same art the
//      terminal TUI prints at boot)
//    * Slim status bar showing agent state + model
//

import SwiftUI

/// The Rich terminal TUI's palette, ported 1:1 so the windowed surface
/// reads as "the same app in a clean window."  Accent is the TUI's
/// ``theme._ACCENT_HEX`` (#3aa0ff); the canvas is a near-black terminal
/// ground rather than the system window colour.
private enum Term {
    static let accent  = Color(red: 0.227, green: 0.627, blue: 1.000) // #3aa0ff
    static let canvas  = Color(red: 0.043, green: 0.055, blue: 0.078) // #0B0E14
    static let panel   = Color(red: 0.075, green: 0.090, blue: 0.122) // #131720
    static let ink     = Color(red: 0.866, green: 0.886, blue: 0.918) // #DDE2EA
    static let inkDim  = Color(red: 0.533, green: 0.560, blue: 0.612) // #888F9C
    static let rule    = Color(red: 0.227, green: 0.627, blue: 1.000).opacity(0.25)
    static let mono    = Font.system(size: 13, design: .monospaced)
}

/// The JAEGER ASCII banner — same art the terminal TUI prints at boot
/// (``interfaces/tui/banner.py``).  Sized small enough that all 70
/// columns fit the chat window's min width.
private struct JaegerBanner: View {
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

struct ChatView: View {
    @EnvironmentObject private var agent: AgentBridge
    @StateObject private var chat: ChatViewModel

    init(agent: AgentBridge) {
        _chat = StateObject(wrappedValue: ChatViewModel(agent: agent))
    }

    var body: some View {
        VStack(spacing: 0) {
            messageList
            Rectangle().fill(Term.rule).frame(height: 1)
            composer
            statusBar
        }
        .frame(minWidth: 540, minHeight: 560)
        .background(Term.canvas)
        // 0.3.0 floating pill ↔ chat hand-off via ``PillBridge``
        // (singleton ``ObservableObject``).  Three things wired here:
        //
        //   1. ``.onAppear`` drains any prompt the pill captured before
        //      this view existed (cold-launch race — when the operator
        //      summons the pill before the chat window has ever been
        //      opened, the controller writes the prompt and THEN
        //      raises the window; this view's first body pass picks
        //      the prompt up here).
        //   2. ``.onChange(of: bridge.pendingPrompt)`` handles
        //      subsequent submits while the chat view is already
        //      mounted.
        //   3. ``.onChange(of: chat.isSending)`` mirrors the chat
        //      model's busy guard into the bridge so the pill's
        //      send button can disable cleanly instead of submissions
        //      silently disappearing into the ``isSending`` no-op.
        .onAppear {
            drainPendingPillPrompt()
            PillBridge.shared.isAgentBusy = chat.isSending
        }
        .onChange(of: PillBridge.shared.pendingPrompt) { _, _ in
            drainPendingPillPrompt()
        }
        .onChange(of: chat.isSending) { _, newValue in
            PillBridge.shared.isAgentBusy = newValue
        }
    }

    /// Pull any pending prompt off the pill bridge, clear it, and
    /// hand it to ``chat.send`` on the main actor.  Idempotent — a
    /// nil pending prompt is a no-op, so binding this to both
    /// ``.onAppear`` and ``.onChange`` is safe.
    private func drainPendingPillPrompt() {
        let bridge = PillBridge.shared
        guard let text = bridge.pendingPrompt,
              !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { return }
        bridge.pendingPrompt = nil
        Task { @MainActor in
            await chat.send(text)
        }
    }

    // MARK: - Sections

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    if chat.messages.isEmpty {
                        emptyState
                            .padding(.top, 40)
                            .frame(maxWidth: .infinity)
                    }
                    ForEach(chat.messages) { msg in
                        TranscriptRow(message: msg)
                            .id(msg.id)
                    }
                }
                .padding(.horizontal, 18)
                .padding(.vertical, 14)
            }
            .onChange(of: chat.messages.count) { _, _ in
                if let last = chat.messages.last {
                    withAnimation(.easeOut(duration: 0.2)) {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 16) {
            JaegerBanner()
            Text(agent.isConnected
                 ? "Type a prompt, or use the floating pill (⌥Space)."
                 : "Agent offline — start it to begin.")
                .font(.system(size: 12, design: .monospaced))
                .foregroundColor(Term.inkDim)
        }
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 8) {
            Text("❯")
                .font(Term.mono.weight(.bold))
                .foregroundColor(Term.accent)
                .padding(.leading, 4)
                .padding(.bottom, 8)

            TextField("Message…", text: $chat.composerText, axis: .vertical)
                .textFieldStyle(.plain)
                .lineLimit(1...6)
                .font(Term.mono)
                .foregroundColor(Term.ink)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(
                    RoundedRectangle(cornerRadius: 8)
                        .fill(Term.panel)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .strokeBorder(borderColor, lineWidth: 1)
                )
                .onSubmit(sendCurrent)

            // Voice toggle button.  Tap to start recording (icon goes
            // red, level bar appears at the composer's bottom edge);
            // tap again to stop and submit the capture.
            //
            // Why tap-to-toggle over press-and-hold: SwiftUI's
            // ``onLongPressGesture(minimumDuration: 0, …)`` combo trips
            // a known Swift-6 strict-concurrency crash on macOS 26
            // (``_checkExpectedExecutor`` blows up during gesture
            // action dispatch). Tap semantics sidestep the bug and are
            // honestly the better fit for a desktop chat window — you
            // shouldn't have to hold a mouse button for a 30-second
            // dictation. Future #2/#3 work may revisit with a custom
            // NSGestureRecognizer-backed PTT if we want hold semantics
            // back.
            Button(action: toggleVoice) {
                Image(systemName: voice.isRecording
                      ? "stop.circle.fill"
                      : "mic.circle.fill")
                    .font(.system(size: 28))
                    .foregroundStyle(voice.isRecording ? .red : .secondary)
                    .symbolEffect(.pulse, isActive: voice.isRecording)
            }
            .buttonStyle(.plain)
            .disabled(!agent.isConnected)
            .help(voice.isRecording ? "Stop recording" : "Start recording")

            Button(action: sendCurrent) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 28))
                    .foregroundColor(canSend ? Term.accent : Term.inkDim)
            }
            .buttonStyle(.plain)
            .disabled(!canSend)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        // Live level meter overlays the bottom edge of the composer
        // while we're recording.  Cheap, accurate, doesn't push the
        // layout around when it appears.
        .overlay(alignment: .bottom) {
            if voice.isRecording {
                LevelBar(level: voice.levelMeter)
                    .frame(height: 2)
                    .padding(.horizontal, 14)
            }
        }
    }

    /// Convenience accessor — the recorder lives on the view model.
    private var voice: VoiceRecorder { chat.voice }

    /// Composer border tints red while recording so the visual
    /// affordance is obvious; goes accent-blue while a STT pass is
    /// in flight.
    private var borderColor: Color {
        if voice.isRecording { return Color.red.opacity(0.55) }
        if chat.isTranscribing { return Term.accent.opacity(0.5) }
        return Term.rule
    }

    /// Toggle voice recording on/off.  Called by the mic button on
    /// each tap.  Synchronous — see VoiceRecorder.swift for the long
    /// version of why we keep this path free of Task creation.
    private func toggleVoice() {
        if voice.isRecording {
            chat.stopVoice()
        } else {
            chat.startVoice()
        }
    }

    private var statusBar: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(agent.isConnected ? Color.green : Term.inkDim)
                .frame(width: 7, height: 7)
            if agent.isConnected {
                Text(agent.status?.modelName ?? "connected")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(Term.inkDim)
                if let inst = agent.status?.instance {
                    Text("· \(inst)")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundColor(Term.inkDim.opacity(0.7))
                }
                if agent.isAgentBooting {
                    // Real signal now: the fast handshake connects before
                    // the model loads; agent_state streams the transition.
                    Text("· warming up…")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundColor(Term.inkDim.opacity(0.7))
                }
            } else {
                Text("agent offline")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(Term.inkDim)
            }
            Spacer()
            if chat.isSending {
                ProgressView()
                    .controlSize(.mini)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 6)
        .background(Term.panel)
    }

    // MARK: - Actions

    private var canSend: Bool {
        agent.isConnected
            && !chat.isSending
            && !chat.isTranscribing
            && !chat.composerText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func sendCurrent() {
        let text = chat.composerText
        chat.composerText = ""
        Task { await chat.send(text) }
    }
}


// MARK: - TranscriptRow

/// One transcript line in the terminal aesthetic.  Roles are left-aligned
/// and prefixed (``❯`` for you, the agent name for replies) rather than
/// bubbled — the windowed echo of the Rich terminal TUI's turn log.
struct TranscriptRow: View {
    let message: ChatMessage

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
    }
}


/// Thin one-pixel bar showing the mic's current peak level — sits
/// at the bottom of the composer field while recording.  Cheap and
/// readable; doesn't compete with the chat content.
private struct LevelBar: View {
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


/// Three pulsing dots while we wait for the agent's reply.
private struct ThinkingDots: View {
    @State private var phase: Int = 0

    var body: some View {
        HStack(spacing: 4) {
            ForEach(0..<3, id: \.self) { i in
                Circle()
                    .fill(Term.accent)
                    .frame(width: 6, height: 6)
                    .opacity(phase == i ? 1.0 : 0.3)
            }
        }
        .onAppear {
            Task {
                while !Task.isCancelled {
                    try? await Task.sleep(nanoseconds: 350_000_000)
                    await MainActor.run { phase = (phase + 1) % 3 }
                }
            }
        }
    }
}
