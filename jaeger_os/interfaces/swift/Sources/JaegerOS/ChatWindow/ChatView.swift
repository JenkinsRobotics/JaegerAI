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
                // Character-first identity, the windowed echo of the rich
                // TUI's "jros · <name> · local" header.
                if let character = agent.status?.character {
                    Text(character)
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        .foregroundColor(Term.accent)
                    Text("·")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundColor(Term.inkDim.opacity(0.7))
                }
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
