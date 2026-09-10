//
//  ChatView.swift
//  JaegerAI / ChatWindow
//
//  Unified desktop chat interface bringing together:
//    1. Agent-centric sidebar (Chief of Staff, Stack Auditor, Release Scribe, Gateway)
//       matching the Hermes WebUI layout.
//    2. ChatGPT-style clean empty state hero ("What's on your mind today?") with quick chips.
//    3. Detached floating pill composer with model selector (Instant ▾), attachment +,
//       live voice transcription, and duplex voice mode.
//

import AppKit
import SwiftUI

// MARK: - Agent Roster Item

struct AgentRosterItem: Identifiable, Hashable {
    let id: String
    let name: String
    let preview: String
    let timestamp: String
    let color: Color
    var unread: Bool
}

// MARK: - ChatView

struct ChatView: View {
    @EnvironmentObject private var agent: AgentBridge
    @StateObject private var chat: ChatViewModel

    @State private var showSidebar = true
    @State private var selectedAgentId = "chief-of-staff"
    @State private var searchText = ""
    @State private var showHistory = false
    @State private var sessions: [SessionSummary] = []
    @State private var sessionsLoaded = false
    @State private var progressExpanded = true
    @State private var attachedURLs: [URL] = []

    @State private var agentRoster: [AgentRosterItem] = [
        AgentRosterItem(
            id: "chief-of-staff",
            name: "Chief of Staff",
            preview: "Audit: Antigravity finish-alpha…",
            timestamp: "1:31 PM",
            color: Color(red: 0.96, green: 0.55, blue: 0.16),
            unread: false
        ),
        AgentRosterItem(
            id: "stack-auditor",
            name: "Stack Auditor",
            preview: "Message from Chief of Staff…",
            timestamp: "1:30 PM",
            color: Color(red: 0.98, green: 0.45, blue: 0.22),
            unread: true
        ),
        AgentRosterItem(
            id: "release-scribe",
            name: "Release Scribe",
            preview: "Updated the held 0.12.0 draft…",
            timestamp: "1:30 AM",
            color: Color(red: 0.95, green: 0.28, blue: 0.38),
            unread: false
        ),
        AgentRosterItem(
            id: "gateway",
            name: "Jaeger Gateway",
            preview: "Messaged Chief of Staff: Active…",
            timestamp: "1:28 AM",
            color: Color(red: 0.55, green: 0.58, blue: 0.62),
            unread: true
        ),
        AgentRosterItem(
            id: "migration-core",
            name: "Jaeger Migration Core",
            preview: "Core migration pass: GO to…",
            timestamp: "1:25 AM",
            color: Color(red: 0.95, green: 0.28, blue: 0.40),
            unread: true
        ),
        AgentRosterItem(
            id: "migration-install",
            name: "Jaeger Migration Install",
            preview: "Standing by for any CoS follow…",
            timestamp: "1:22 AM",
            color: Color(red: 0.72, green: 0.52, blue: 0.38),
            unread: false
        ),
        AgentRosterItem(
            id: "migration-webui",
            name: "Jaeger Migration WebUI",
            preview: "Reported to CoS. Standing…",
            timestamp: "1:20 AM",
            color: Color(red: 0.52, green: 0.58, blue: 0.64),
            unread: true
        ),
        AgentRosterItem(
            id: "migration-router",
            name: "Jaeger Migration Router",
            preview: "Told Chief of Staff: recommend…",
            timestamp: "1:20 AM",
            color: Color(red: 0.20, green: 0.78, blue: 0.55),
            unread: false
        ),
        AgentRosterItem(
            id: "surfaces-bar",
            name: "Jaeger Surfaces Bar",
            preview: "Message from Jaeger Surface…",
            timestamp: "1:19 AM",
            color: Color(red: 0.55, green: 0.58, blue: 0.62),
            unread: false
        ),
        AgentRosterItem(
            id: "migration-si",
            name: "Jaeger Migration SI",
            preview: "Messaged Chief of Staff: #…",
            timestamp: "1:18 AM",
            color: Color(red: 0.98, green: 0.45, blue: 0.22),
            unread: true
        )
    ]

    init(agent: AgentBridge) {
        _chat = StateObject(wrappedValue: ChatViewModel(agent: agent))
    }

    private var selectedAgent: AgentRosterItem {
        agentRoster.first(where: { $0.id == selectedAgentId }) ?? agentRoster[0]
    }

    private var filteredAgents: [AgentRosterItem] {
        let q = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if q.isEmpty { return agentRoster }
        return agentRoster.filter {
            $0.name.lowercased().contains(q) || $0.preview.lowercased().contains(q)
        }
    }

    private var currentModelShortName: String {
        guard let name = agent.status?.modelName else { return "Instant" }
        if name.contains("flash") { return "Flash" }
        if name.contains("gemma") { return "Gemma" }
        if name.contains("kimi") { return "Kimi" }
        if name.contains("qwen") { return "Qwen" }
        return name.components(separatedBy: ":").first ?? "Instant"
    }

    var body: some View {
        HStack(spacing: 0) {
            if showSidebar {
                sidebarView
                    .frame(width: 250)
                    .transition(.move(edge: .leading).combined(with: .opacity))
                Rectangle().fill(Color.white.opacity(0.06)).frame(width: 1)
            }

            VStack(spacing: 0) {
                mainToolbar
                if let progress = agent.taskProgress {
                    TaskProgressDrawer(progress: progress, expanded: $progressExpanded)
                }
                Rectangle().fill(Color.white.opacity(0.06)).frame(height: 1)

                if chat.messages.isEmpty {
                    emptyStateHero
                } else {
                    messageList
                    Rectangle().fill(Color.white.opacity(0.04)).frame(height: 1)
                    slashPalette
                    floatingComposer
                }

                statusBar
            }
        }
        .frame(minWidth: 640, minHeight: 520)
        .background(Term.canvas)
        .onAppear {
            drainPendingPillPrompt()
            PillBridge.shared.isAgentBusy = chat.isSending
            Task { await loadLiveAgentsFromGateway() }
        }
        .onChange(of: PillBridge.shared.pendingPrompt) { _, _ in
            drainPendingPillPrompt()
        }
        .onChange(of: chat.isSending) { _, newValue in
            PillBridge.shared.isAgentBusy = newValue
        }
        .sheet(item: approvalRequest) { request in
            ApprovalSheetView(request: request) { answer in
                if chat.sessionKey == "dispatcher" {
                    chat.controlDispatcher("approval", approval: request, choice: answer)
                } else {
                    agent.respond(to: request, answer: answer)
                }
            }
        }
        .sheet(isPresented: $chat.showModelPicker) {
            ModelPickerSheet(agent: agent, onDismiss: {
                chat.showModelPicker = false
            }, onSwitched: { line in
                chat.appendSystem(line)
            })
        }
    }

    // MARK: - Sidebar View (Image 1 reference)

    private var sidebarView: some View {
        VStack(spacing: 0) {
            // Search row + New Chat
            HStack(spacing: 8) {
                HStack(spacing: 6) {
                    Image(systemName: "magnifyingglass")
                        .font(.system(size: 11))
                        .foregroundColor(Term.inkDim)
                    TextField("Search", text: $searchText)
                        .textFieldStyle(.plain)
                        .font(.system(size: 12))
                        .foregroundColor(Term.ink)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color.white.opacity(0.05)))

                Button(action: startNewChat) {
                    Image(systemName: "plus")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundColor(Term.inkDim)
                        .padding(6)
                        .background(RoundedRectangle(cornerRadius: 6).fill(Color.white.opacity(0.05)))
                }
                .buttonStyle(.plain)
                .help("New Chat")
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)

            Rectangle().fill(Color.white.opacity(0.05)).frame(height: 1)

            // Agent roster list
            ScrollView {
                LazyVStack(spacing: 2) {
                    ForEach(filteredAgents) { item in
                        agentRow(item)
                    }
                }
                .padding(.vertical, 6)
                .padding(.horizontal, 8)
            }

            Rectangle().fill(Color.white.opacity(0.05)).frame(height: 1)

            // Sidebar footer
            VStack(spacing: 8) {
                Button(action: {}) {
                    HStack(spacing: 10) {
                        Image(systemName: "square.grid.2x2")
                            .font(.system(size: 13))
                            .foregroundColor(Term.inkDim)
                        Text("Marketplace")
                            .font(.system(size: 12, weight: .medium))
                            .foregroundColor(Term.ink)
                        Spacer()
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)

                HStack(spacing: 10) {
                    ZStack {
                        Circle()
                            .fill(Color.white.opacity(0.12))
                            .frame(width: 26, height: 26)
                        Text("MJ")
                            .font(.system(size: 11, weight: .bold))
                            .foregroundColor(Term.ink)
                    }
                    VStack(alignment: .leading, spacing: 1) {
                        Text("Matthew Jenkins")
                            .font(.system(size: 12, weight: .medium))
                            .foregroundColor(Term.ink)
                        HStack(spacing: 4) {
                            Circle()
                                .fill(Color.green)
                                .frame(width: 6, height: 6)
                            Text("Online")
                                .font(.system(size: 10))
                                .foregroundColor(Term.inkDim)
                        }
                    }
                    Spacer()
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 4)
            }
            .padding(8)
            .background(Color.white.opacity(0.02))
        }
        .background(Color(red: 0.06, green: 0.07, blue: 0.09))
    }

    private func agentRow(_ item: AgentRosterItem) -> some View {
        let isSelected = item.id == selectedAgentId
        return Button {
            selectedAgentId = item.id
            if item.id == "gateway" || item.id == "chief-of-staff" {
                Task { await chat.loadSession(item.id) }
            }
        } label: {
            HStack(alignment: .center, spacing: 10) {
                // Hexagonal badge icon
                ZStack {
                    Image(systemName: "hexagon.fill")
                        .font(.system(size: 24))
                        .foregroundColor(item.color)
                    Image(systemName: "sparkles")
                        .font(.system(size: 10))
                        .foregroundColor(.white)
                }

                VStack(alignment: .leading, spacing: 2) {
                    HStack {
                        Text(item.name)
                            .font(.system(size: 12, weight: isSelected ? .bold : .medium))
                            .foregroundColor(isSelected ? Term.accent : Term.ink)
                            .lineLimit(1)
                        Spacer()
                        Text(item.timestamp)
                            .font(.system(size: 10))
                            .foregroundColor(Term.inkDim.opacity(0.7))
                    }
                    HStack {
                        Text(item.preview)
                            .font(.system(size: 11))
                            .foregroundColor(Term.inkDim)
                            .lineLimit(1)
                        Spacer()
                        if item.unread {
                            Circle()
                                .fill(Color.blue)
                                .frame(width: 6, height: 6)
                        }
                    }
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(isSelected ? Color.white.opacity(0.08) : Color.clear)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    // MARK: - Main Toolbar

    private var mainToolbar: some View {
        HStack(spacing: 12) {
            Button(action: { withAnimation(.easeInOut(duration: 0.18)) { showSidebar.toggle() } }) {
                Image(systemName: "sidebar.leading")
                    .font(.system(size: 13))
                    .foregroundColor(Term.inkDim)
            }
            .buttonStyle(.plain)
            .help("Toggle Sidebar")

            // Active agent indicator
            HStack(spacing: 8) {
                Image(systemName: "hexagon.fill")
                    .font(.system(size: 16))
                    .foregroundColor(selectedAgent.color)
                Text(selectedAgent.name)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundColor(Term.ink)
            }

            // Model selector pill (Instant ▾)
            Button(action: { chat.showModelPicker = true }) {
                HStack(spacing: 4) {
                    Text(currentModelShortName)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(Term.inkDim)
                    Image(systemName: "chevron.down")
                        .font(.system(size: 8, weight: .bold))
                        .foregroundColor(Term.inkDim.opacity(0.8))
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(Capsule().fill(Color.white.opacity(0.06)))
            }
            .buttonStyle(.plain)
            .help("Switch model")

            if chat.sessionKey == "dispatcher" {
                VStack(alignment: .leading, spacing: 1) {
                    Text(chat.dispatcherStatus).font(.caption).lineLimit(1)
                    if chat.dispatcherRun?.active == true, let tool = chat.dispatcherRun?.tools?.last {
                        Text((tool.tool ?? "Tool") + " · " + tool.event).font(.caption2)
                    }
                }
                if chat.dispatcherRun?.active == true {
                    Button(chat.dispatcherRun?.status == "interrupted" ? "Check status" : "Stop") {
                        chat.controlDispatcher(chat.dispatcherRun?.status == "interrupted" ? "reconcile" : "cancel")
                    }
                    .buttonStyle(.plain)
                }
            }

            Spacer()

            Button(action: startNewChat) {
                Image(systemName: "square.and.pencil")
                    .font(.system(size: 13))
                    .foregroundColor(Term.inkDim)
            }
            .buttonStyle(.plain)
            .help("New Chat")
            .disabled(chat.isSwitchingSession || chat.isSending)

            Button(action: openHistory) {
                Image(systemName: "clock.arrow.circlepath")
                    .font(.system(size: 13))
                    .foregroundColor(Term.inkDim)
            }
            .buttonStyle(.plain)
            .help("History")
            .disabled(chat.isSwitchingSession || chat.isSending)
            .popover(isPresented: $showHistory, arrowEdge: .bottom) {
                historyList
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(Color(red: 0.05, green: 0.06, blue: 0.08))
    }

    // MARK: - Empty State Hero (Image 2 reference)

    private var emptyStateHero: some View {
        VStack(spacing: 28) {
            Spacer()

            VStack(spacing: 8) {
                Text("What's on your mind today?")
                    .font(.system(size: 28, weight: .semibold))
                    .foregroundColor(Term.ink)
                Text("Collaborating with \(selectedAgent.name)")
                    .font(.system(size: 13))
                    .foregroundColor(Term.inkDim)
            }

            // Quick suggestion chips
            HStack(spacing: 8) {
                suggestionChip(title: "Audit repo hygiene", icon: "shield.checkerboard") {
                    chat.composerText = "Audit repository hygiene and check all test suites"
                }
                suggestionChip(title: "Review release draft", icon: "doc.text") {
                    chat.composerText = "Review the release draft and summarize changes"
                }
                suggestionChip(title: "Check model router", icon: "network") {
                    chat.composerText = "Check model router endpoints and active models"
                }
            }

            // Hero composer pill
            floatingComposer
                .frame(maxWidth: 580)

            Spacer()
        }
        .padding(.horizontal, 24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func suggestionChip(title: String, icon: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: icon)
                    .font(.system(size: 11))
                    .foregroundColor(Term.accent)
                Text(title)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundColor(Term.ink)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: 16)
                    .fill(Color.white.opacity(0.05))
                    .overlay(
                        RoundedRectangle(cornerRadius: 16)
                            .stroke(Color.white.opacity(0.08), lineWidth: 1)
                    )
            )
        }
        .buttonStyle(.plain)
    }

    // MARK: - Floating Capsule Composer (Image 1 & 2 reference)

    private var floatingComposer: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !attachedURLs.isEmpty {
                attachmentChips
            }

            HStack(alignment: .center, spacing: 8) {
                // Plus attachment button
                Button(action: pickAttachments) {
                    Image(systemName: "plus")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundColor(Term.inkDim)
                        .padding(6)
                        .background(Circle().fill(Color.white.opacity(0.06)))
                }
                .buttonStyle(.plain)
                .help("Attach files")
                .disabled(!agent.isConnected)

                // Input text field
                TextField(
                    text: $chat.composerText,
                    prompt: Text("Message \(selectedAgent.name)…").foregroundColor(Term.inkDim.opacity(0.8)),
                    axis: .vertical
                ) { Text("Message") }
                    .textFieldStyle(.plain)
                    .lineLimit(1...5)
                    .font(.system(size: 14))
                    .foregroundColor(Term.ink)
                    .tint(Term.accent)
                    .onSubmit(sendCurrent)

                Spacer(minLength: 4)

                // Model Selector pill inside composer
                Button(action: { chat.showModelPicker = true }) {
                    HStack(spacing: 3) {
                        Text(currentModelShortName)
                            .font(.system(size: 11, weight: .medium))
                            .foregroundColor(Term.inkDim)
                        Image(systemName: "chevron.down")
                            .font(.system(size: 8, weight: .bold))
                            .foregroundColor(Term.inkDim.opacity(0.8))
                    }
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Capsule().fill(Color.white.opacity(0.06)))
                }
                .buttonStyle(.plain)

                // Voice mic tap toggle
                Button(action: toggleVoice) {
                    Image(systemName: voice.isRecording ? "stop.circle.fill" : "mic.fill")
                        .font(.system(size: 14))
                        .foregroundColor(voice.isRecording ? Color.red : Term.inkDim)
                        .padding(6)
                }
                .buttonStyle(.plain)
                .disabled(!agent.isConnected)
                .help(voice.isRecording ? "Stop recording" : "Dictate prompt")

                // Blue duplex audio wave button (Image 2 voice mode)
                Button(action: toggleVoice) {
                    ZStack {
                        Circle()
                            .fill(voice.isRecording ? Color.red : Term.accent)
                            .frame(width: 28, height: 28)
                        Image(systemName: "waveform")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundColor(.white)
                    }
                }
                .buttonStyle(.plain)
                .help("Voice Mode")

                // Send button
                if canSend {
                    Button(action: sendCurrent) {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.system(size: 26))
                            .foregroundColor(Term.accent)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: 22)
                    .fill(Color(red: 0.10, green: 0.11, blue: 0.14))
                    .overlay(
                        RoundedRectangle(cornerRadius: 22)
                            .strokeBorder(borderColor, lineWidth: 1)
                    )
                    .shadow(color: Color.black.opacity(0.35), radius: 10, x: 0, y: 4)
            )
            .overlay(alignment: .bottom) {
                if voice.isRecording {
                    LevelBar(level: voice.levelMeter)
                        .frame(height: 2)
                        .padding(.horizontal, 16)
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }

    // MARK: - Message List

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    ForEach(chat.messages) { msg in
                        TranscriptRow(
                            message: msg,
                            showTurnRule: chat.turnSeparators
                                && msg.author == .user
                                && msg.id != chat.messages.first?.id
                        )
                        .id(msg.id)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 16)
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

    // MARK: - Status Bar

    private var statusBar: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(agent.isConnected ? Color.green : Term.inkDim)
                .frame(width: 7, height: 7)

            if agent.isConnected {
                if let name = agent.status?.displayName {
                    Text(name)
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
                    Text("· warming up…")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundColor(Term.inkDim.opacity(0.7))
                }
            } else {
                Text("agent offline")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(Term.inkDim)
            }

            Menu {
                ForEach(OperatingMode.allCases) { mode in
                    Button(action: { chat.setOperatingMode(mode) }) {
                        HStack {
                            Text("\(mode.badgeText) · \(mode.summary)")
                            if chat.operatingMode == mode {
                                Image(systemName: "checkmark")
                            }
                        }
                    }
                }
            } label: {
                Text(chat.operatingMode.badgeText)
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(
                        Capsule()
                            .fill(Term.panel)
                            .overlay(Capsule().stroke(Term.rule, lineWidth: 1))
                    )
            }
            .menuStyle(.borderlessButton)

            Spacer()

            if let ctx = chat.contextUsage {
                Text("ctx \(ChatViewModel.fmtTokens(ctx.used))/\(ChatViewModel.fmtTokens(ctx.max))")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(Term.inkDim)
            }

            if chat.isSending {
                ProgressView().controlSize(.mini)
            }

            if !chat.pendingSends.isEmpty {
                Text("· \(chat.pendingSends.count) queued")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(Term.inkDim)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 6)
        .background(Color(red: 0.05, green: 0.06, blue: 0.08))
    }

    // MARK: - Slash Palette

    @ViewBuilder
    private var slashPalette: some View {
        let matches = SlashRouting.matchingPalette(chat.composerText)
        if !matches.isEmpty {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(matches) { item in
                    Button {
                        pickSlash(item)
                    } label: {
                        HStack(spacing: 10) {
                            Text("/\(item.name)")
                                .font(.system(size: 12, weight: .semibold, design: .monospaced))
                                .foregroundColor(Term.accent)
                            Text(item.summary)
                                .font(.system(size: 12, design: .monospaced))
                                .foregroundColor(Term.inkDim)
                                .lineLimit(1)
                            Spacer()
                        }
                        .padding(.horizontal, 14)
                        .padding(.vertical, 7)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
            .background(Term.panel)
        }
    }

    private func pickSlash(_ item: SlashRouting.Item) {
        switch item.name {
        case "model", "models":
            chat.composerText = ""
            chat.showModelPicker = true
        case "new":
            chat.composerText = ""
            startNewChat()
        case "goal", "plan", "deepthink", "mode", "steer":
            chat.composerText = "/\(item.name) "
        default:
            chat.composerText = "/\(item.name)"
        }
    }

    // MARK: - History Popover

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

    // MARK: - Helpers & Actions

    private var attachmentChips: some View {
        HStack(spacing: 6) {
            ForEach(attachedURLs, id: \.path) { url in
                HStack(spacing: 4) {
                    Image(systemName: "doc")
                        .font(.system(size: 10))
                    Text(url.lastPathComponent)
                        .font(.system(size: 11, design: .monospaced))
                        .lineLimit(1)
                    Button {
                        attachedURLs.removeAll { $0 == url }
                    } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 8, weight: .bold))
                    }
                    .buttonStyle(.plain)
                }
                .foregroundColor(Term.inkDim)
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(Capsule().fill(Term.panel))
            }
        }
        .padding(.leading, 8)
    }

    private func pickAttachments() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.prompt = "Attach"
        guard panel.runModal() == .OK else { return }
        for url in panel.urls where !attachedURLs.contains(url) {
            attachedURLs.append(url)
        }
    }

    private var voice: VoiceRecorder { chat.voice }

    private var borderColor: Color {
        if voice.isRecording { return Color.red.opacity(0.6) }
        if chat.isTranscribing { return Term.accent.opacity(0.6) }
        return Color.white.opacity(0.09)
    }

    private func toggleVoice() {
        if voice.isRecording {
            chat.stopVoice()
        } else {
            chat.startVoice()
        }
    }

    private var canSend: Bool {
        agent.isConnected
            && !chat.isTranscribing
            && (!chat.composerText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || !attachedURLs.isEmpty)
    }

    private func sendCurrent() {
        var text = chat.composerText
        if !attachedURLs.isEmpty {
            let listing = attachedURLs.map { "- \($0.path)" }.joined(separator: "\n")
            let body = text.trimmingCharacters(in: .whitespacesAndNewlines)
            text = "Attached files:\n\(listing)" + (body.isEmpty ? "" : "\n\n\(body)")
            attachedURLs = []
        }
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

    private func refreshHistoryIfNeeded(force: Bool = false) async {
        guard force || !sessionsLoaded else { return }
        sessions = await chat.fetchSessions()
        sessionsLoaded = true
    }

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

    private func loadLiveAgentsFromGateway() async {
        do {
            let catalog = try await GatewayClient.fromEnvironment().listAgents()
            var merged: [AgentRosterItem] = []
            let allLive = (catalog.agents ?? []) + (catalog.jaeger_native ?? []) + (catalog.third_party ?? [])
            for a in allLive {
                let color: Color = a.kind == "gateway" ? Color(red: 0.55, green: 0.58, blue: 0.62)
                    : (a.kind == "lead" ? Color(red: 0.96, green: 0.55, blue: 0.16)
                    : Color(red: 0.20, green: 0.78, blue: 0.55))
                merged.append(
                    AgentRosterItem(
                        id: a.id,
                        name: a.displayName,
                        preview: "Agent online (\(a.kind))",
                        timestamp: "Now",
                        color: color,
                        unread: a.active == true
                    )
                )
            }
            if !merged.isEmpty {
                // Prepend or merge with current roster
                var current = agentRoster
                for m in merged {
                    if !current.contains(where: { $0.id == m.id }) {
                        current.insert(m, at: 0)
                    }
                }
                agentRoster = current
            }
        } catch {
            // Keep default curated roster
        }
    }

    private var approvalRequest: Binding<BridgeRequest?> {
        Binding(
            get: {
                if chat.sessionKey == "dispatcher" { return chat.dispatcherApproval }
                guard let req = agent.pendingRequest, req.kind == "approval" else { return nil }
                return req
            },
            set: { newValue in
                if newValue == nil, let req = chat.dispatcherApproval, chat.sessionKey == "dispatcher" {
                    chat.controlDispatcher("approval", approval: req, choice: "deny")
                    return
                }
                if newValue == nil, let req = agent.pendingRequest, req.kind == "approval" {
                    agent.respond(to: req, answer: "deny")
                }
            }
        )
    }
}

// MARK: - Live Task Progress Drawer

private struct TaskProgressDrawer: View {
    let progress: ToolProgress
    @Binding var expanded: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button {
                withAnimation(.easeOut(duration: 0.15)) { expanded.toggle() }
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: expanded ? "chevron.down" : "chevron.right")
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundColor(Term.inkDim)
                    Image(systemName: progress.completed ? "checkmark.circle.fill" : "circle.dotted")
                        .font(.system(size: 11))
                        .foregroundColor(progress.completed ? Color.green : Term.accent)
                    Text(progress.title)
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        .foregroundColor(Term.ink)
                        .lineLimit(1)
                    Spacer()
                    Text(progress.countLabel)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundColor(Term.accent)
                    if progress.total > 0 {
                        Text("\(Int((progress.fraction * 100).rounded()))%")
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundColor(Term.inkDim)
                    }
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if expanded {
                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        Capsule().fill(Term.rule)
                        Capsule()
                            .fill(progress.completed ? Color.green.opacity(0.85) : Term.accent)
                            .frame(width: max(4, geo.size.width * progress.fraction))
                    }
                }
                .frame(height: 6)

                HStack(spacing: 10) {
                    if !progress.currentItem.isEmpty {
                        Text("now \(progress.currentItem)").lineLimit(1)
                    }
                    if progress.remaining > 0 {
                        Text("\(progress.remaining) left")
                    }
                    if !progress.state.isEmpty {
                        Text(progress.state.lowercased())
                    }
                    Spacer()
                }
                .font(.system(size: 10, design: .monospaced))
                .foregroundColor(Term.inkDim)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(Term.panel)
    }
}

// MARK: - Approval Sheet

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
