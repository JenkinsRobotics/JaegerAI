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

    /// History popover state — owned by the view (not the view model):
    /// it's presentation, not conversation state.
    @State private var showHistory = false
    @State private var sessions: [SessionSummary] = []
    @State private var sessionsLoaded = false

    init(agent: AgentBridge) {
        _chat = StateObject(wrappedValue: ChatViewModel(agent: agent))
    }

    var body: some View {
        VStack(spacing: 0) {
            chatToolbar
            Rectangle().fill(Term.rule).frame(height: 1)
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
        // 0.9.3 Task 1 — the headless confirmation surface: a tier-2+
        // permission request (``open_on_host``, …) renders as a sheet
        // right here instead of failing closed. ``approvalRequest``
        // filters ``agent.pendingRequest`` down to kind=="approval";
        // clarify/secret stay UI-less for now, same as before this sheet
        // existed.
        .sheet(item: approvalRequest) { request in
            ApprovalSheetView(request: request) { answer in
                agent.respond(to: request, answer: answer)
            }
        }
    }

    /// Dismissing the sheet WITHOUT tapping a button (Esc, click-away)
    /// answers "deny" — fail-safe, never leaves the agent's turn hanging
    /// past the provider's own 120s timeout.
    private var approvalRequest: Binding<BridgeRequest?> {
        Binding(
            get: {
                guard let req = agent.pendingRequest, req.kind == "approval" else { return nil }
                return req
            },
            set: { newValue in
                if newValue == nil, let req = agent.pendingRequest, req.kind == "approval" {
                    agent.respond(to: req, answer: "deny")
                }
            }
        )
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

    /// Thin header row: New Chat + History — the native app's take on
    /// the PySide6 rich_tui window's ``/new`` and ``/sessions`` slash
    /// commands (interfaces/pyside6/rich_tui/window.py).
    private var chatToolbar: some View {
        HStack(spacing: 10) {
            Button(action: startNewChat) {
                Label("New Chat", systemImage: "square.and.pencil")
                    .font(.system(size: 11, design: .monospaced))
            }
            .buttonStyle(.plain)
            .foregroundColor(Term.inkDim)
            .disabled(chat.isSwitchingSession)

            Spacer()

            Button(action: openHistory) {
                Label("History", systemImage: "clock.arrow.circlepath")
                    .font(.system(size: 11, design: .monospaced))
            }
            .buttonStyle(.plain)
            .foregroundColor(Term.inkDim)
            .disabled(chat.isSwitchingSession)
            .popover(isPresented: $showHistory, arrowEdge: .bottom) {
                historyList
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(Term.panel)
    }

    private var historyList: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Recent conversations")
                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                .foregroundColor(Term.inkDim)
                .padding(12)
            Divider()
            if sessions.isEmpty {
                Text(sessionsLoaded ? "No past conversations yet." : "Loading…")
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundColor(Term.inkDim)
                    .padding(16)
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(sessions) { row in
                            historyRow(row)
                            Divider()
                        }
                    }
                }
                .frame(maxHeight: 320)
            }
        }
        .frame(width: 320)
        .background(Term.canvas)
        .task { await refreshHistoryIfNeeded() }
    }

    private func historyRow(_ row: SessionSummary) -> some View {
        Button {
            Task {
                showHistory = false
                await chat.loadSession(row.id)
            }
        } label: {
            VStack(alignment: .leading, spacing: 3) {
                HStack {
                    Text(row.displayTitle)
                        .font(.system(size: 12, weight: .medium, design: .monospaced))
                        .foregroundColor(row.id == chat.sessionKey ? Term.accent : Term.ink)
                        .lineLimit(1)
                    Spacer()
                    Text("\(row.messages)")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundColor(Term.inkDim.opacity(0.7))
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

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
                        TranscriptRow(
                            message: msg,
                            // Thin accent rule before every turn after the
                            // first — config-gated (display.turn_separators).
                            showTurnRule: chat.turnSeparators
                                && msg.author == .user
                                && msg.id != chat.messages.first?.id
                        )
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

            // Explicit prompt Text: the default placeholder renders in the
            // system's label colour, which collapses to near-black on the
            // Term.canvas ground when the window inherits a light
            // appearance. Styling it Term.inkDim keeps it legible no
            // matter what appearance AppKit hands us.
            TextField(text: $chat.composerText,
                      prompt: Text("Message…").foregroundColor(Term.inkDim),
                      axis: .vertical) { Text("Message") }
                .textFieldStyle(.plain)
                .lineLimit(1...6)
                .font(Term.mono)
                .foregroundColor(Term.ink)
                .tint(Term.accent)
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
                    // Term palette, not `.secondary` — the system secondary
                    // colour is a dark grey under a light appearance and
                    // vanishes on the dark canvas.
                    .foregroundStyle(voice.isRecording ? Color.red : Term.inkDim)
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
                // AGENT-name-first identity (identity.yaml — the robot the
                // operator named), with the character as secondary flavor:
                // "Ted · playing HAL 9000 · <model>".
                if let name = agent.status?.displayName {
                    Text(name)
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        .foregroundColor(Term.accent)
                    if let character = agent.status?.character,
                       character.caseInsensitiveCompare(name) != .orderedSame {
                        Text("· playing \(character)")
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundColor(Term.inkDim)
                    }
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
            // Context gauge — the TUI status bar's "ctx 18.3K/32.8K",
            // fed by the reply frame's v1 telemetry.
            if let ctx = chat.contextUsage {
                Text("ctx \(ChatViewModel.fmtTokens(ctx.used))/\(ChatViewModel.fmtTokens(ctx.max))")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(Term.inkDim)
            }
            if chat.isSending {
                ProgressView()
                    .controlSize(.mini)
            }
            // 0.8.1 item 9: messages typed while the current turn is
            // still running are queued, not dropped — surface that so
            // it doesn't look like they vanished.
            if !chat.pendingSends.isEmpty {
                Text("· \(chat.pendingSends.count) queued")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(Term.inkDim)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 6)
        .background(Term.panel)
    }

    // MARK: - Actions

    private var canSend: Bool {
        // 0.8.1 item 9: sending while a turn is already in flight now
        // QUEUES (ChatViewModel.send) instead of being dropped, so the
        // button stays live through isSending — only a transcription in
        // flight or an empty composer blocks it.
        agent.isConnected
            && !chat.isTranscribing
            && !chat.composerText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func sendCurrent() {
        let text = chat.composerText
        chat.composerText = ""
        Task { await chat.send(text) }
    }

    private func startNewChat() {
        Task { await chat.newChat() }
    }

    private func openHistory() {
        showHistory = true
        Task { await refreshHistoryIfNeeded(force: true) }
    }

    /// Fetch once on first open; ``force`` re-fetches (used when the
    /// operator re-opens History mid-session so a just-created chat
    /// shows up without restarting the app).
    private func refreshHistoryIfNeeded(force: Bool = false) async {
        guard force || !sessionsLoaded else { return }
        sessions = await chat.fetchSessions()
        sessionsLoaded = true
    }
}

// MARK: - Approval sheet

/// The in-chat confirmation surface for a tier-2+ permission request
/// (0.9.3 Task 1 — unblocks ``open_on_host`` and every other gated tool on
/// a bridge/GUI station, which previously had no console to prompt at and
/// failed closed). Thin by design: renders the frame's prompt, sends back
/// whichever button was tapped — no local policy, no caching, the Python
/// side owns every decision (grant persistence included).
private struct ApprovalSheetView: View {
    let request: BridgeRequest
    let respond: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Jaeger wants to…")
                .font(.system(size: 12, weight: .semibold, design: .monospaced))
                .foregroundColor(Term.inkDim)
            Text(request.prompt)
                .font(.system(size: 15, design: .monospaced))
                .foregroundColor(Term.ink)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 10) {
                Spacer()
                Button("Deny") { respond("deny") }
                    .keyboardShortcut(.cancelAction)
                Button("Always Allow") { respond("always") }
                Button("Approve Once") { respond("once") }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
                    .tint(Term.accent)
            }
        }
        .padding(20)
        .frame(width: 380)
        .background(Term.canvas)
    }
}
