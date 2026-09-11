//
//  ChatView.swift
//  JaegerAI / ChatWindow
//
//  Unified desktop chat interface bringing together:
//    1. Sidebar: PINNED (primary assistant displayName + Monarch), PROJECTS from
//       ~/.jaeger/desktop/projects.json, optional AGENTS from Gateway when up,
//       and RECENT sessions (no fake roster when gateway is down).
//    2. ChatGPT-style clean empty state hero ("What's on your mind today?") with quick chips.
//    3. Detached floating pill composer with model selector (Instant ▾), attachment +,
//       live voice transcription, and duplex voice mode.
//    4. Chat / Avatar / Work stage nav.
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

struct DesktopProject: Identifiable, Hashable, Codable {
    var id: String { name }
    let name: String
    let icon: String
    let prompt: String
}

// MARK: - ChatView

struct ChatView: View {
    @EnvironmentObject private var agent: AgentBridge
    @StateObject private var chat: ChatViewModel
    @ObservedObject private var tabState = ChatViewTabState.shared
    @ObservedObject private var tts = TTSManager.shared

    @State private var showSidebar = true
    @State private var selectedSessionId: String? = nil
    @State private var selectedAgentId = "native:jaeger"
    @State private var searchText = ""
    @State private var showHistory = false
    @State private var sessions: [SessionSummary] = []
    @State private var sessionsLoaded = false
    @State private var progressExpanded = true
    @State private var attachedURLs: [URL] = []
    @State private var showMonarchAuthSheet = false
    @State private var micOn = false
    @State private var expandedProjects: Set<String> = []
    @State private var desktopProjects: [DesktopProject] = DesktopProjectStore.defaults
    @State private var gatewayAgentsAvailable = false

    @State private var agentRoster: [AgentRosterItem] = []

    init(agent: AgentBridge) {
        _chat = StateObject(wrappedValue: ChatViewModel(agent: agent))
    }

    private var activeAgentName: String {
        agent.status?.displayName ?? "Chief of Staff"
    }

    private var activeAgentColor: Color {
        Color(red: 0.96, green: 0.55, blue: 0.16)
    }

    private var selectedAgent: AgentRosterItem {
        AgentRosterItem(
            id: selectedAgentId,
            name: activeAgentName,
            preview: "Primary Assistant",
            timestamp: "Active",
            color: activeAgentColor,
            unread: false
        )
    }

    private var filteredSessions: [SessionSummary] {
        let q = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if q.isEmpty { return sessions }
        return sessions.filter {
            $0.displayTitle.lowercased().contains(q) || ($0.preview?.lowercased().contains(q) ?? false)
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

                switch tabState.currentTab {
                case .chat:
                    if chat.messages.isEmpty {
                        emptyStateHero
                    } else {
                        messageList
                        Rectangle().fill(Color.white.opacity(0.04)).frame(height: 1)
                        slashPalette
                        floatingComposer
                    }
                case .avatar:
                    avatarStageView
                case .work:
                    workStageView
                }

                statusBar
            }
        }
        .frame(minWidth: 640, minHeight: 520)
        .background(Term.canvas)
        .onAppear {
            drainPendingPillPrompt()
            PillBridge.shared.isAgentBusy = chat.isSending
            desktopProjects = DesktopProjectStore.loadOrMigrate()
            if expandedProjects.isEmpty {
                expandedProjects = Set(desktopProjects.prefix(2).map(\.name))
            }
            Task {
                await refreshHistoryIfNeeded(force: true)
                await loadLiveAgentsFromGateway()
            }
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
        .sheet(isPresented: $showMonarchAuthSheet) {
            MonarchAuthSheet(
                onDismiss: { showMonarchAuthSheet = false },
                onConnected: { count in
                    chat.appendSystem("✦ Monarch Money connected! Found \(count) account(s). You can now ask about your net worth, balances, and budgets.")
                }
            )
        }
    }

    // MARK: - Sidebar View

    private var sidebarView: some View {
        VStack(spacing: 0) {
            // Header: Search + New Chat
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

            // Sections: PINNED, PROJECTS, RECENT
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    // PINNED SECTION
                    VStack(alignment: .leading, spacing: 3) {
                        Text("PINNED")
                            .font(.system(size: 10, weight: .bold))
                            .foregroundColor(Term.inkDim.opacity(0.6))
                            .padding(.horizontal, 12)

                        // 1. Primary Assistant
                        Button {
                            tabState.currentTab = .chat
                            startNewChat()
                        } label: {
                            HStack(spacing: 8) {
                                Image(systemName: "sparkles")
                                    .font(.system(size: 12))
                                    .foregroundColor(activeAgentColor)
                                    .frame(width: 18)
                                Text(activeAgentName)
                                    .font(.system(size: 12, weight: .medium))
                                    .foregroundColor(Term.ink)
                                    .lineLimit(1)
                                Spacer()
                            }
                            .padding(.horizontal, 10)
                            .padding(.vertical, 6)
                            .background(RoundedRectangle(cornerRadius: 6).fill(chat.messages.isEmpty && tabState.currentTab == .chat ? Color.white.opacity(0.08) : Color.clear))
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)

                        // 2. Financial Monitor (Monarch Money)
                        Button {
                            showMonarchAuthSheet = true
                        } label: {
                            HStack(spacing: 8) {
                                Image(systemName: "creditcard.fill")
                                    .font(.system(size: 11))
                                    .foregroundColor(Color.green)
                                    .frame(width: 18)
                                Text("Financial Monitor")
                                    .font(.system(size: 12, weight: .medium))
                                    .foregroundColor(Term.ink)
                                    .lineLimit(1)
                                Spacer()
                                Circle()
                                    .fill(Color.green.opacity(0.8))
                                    .frame(width: 6, height: 6)
                            }
                            .padding(.horizontal, 10)
                            .padding(.vertical, 6)
                            .background(RoundedRectangle(cornerRadius: 6).fill(Color.clear))
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }

                    // PROJECTS SECTION (from ~/.jaeger/desktop/projects.json)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("PROJECTS")
                            .font(.system(size: 10, weight: .bold))
                            .foregroundColor(Term.inkDim.opacity(0.6))
                            .padding(.horizontal, 12)

                        ForEach(desktopProjects) { project in
                            projectFolderRow(name: project.name, icon: project.icon, prompt: project.prompt)
                        }
                    }

                    // AGENTS SECTION — only when Gateway lists live agents (no fake roster)
                    if gatewayAgentsAvailable && !agentRoster.isEmpty {
                        VStack(alignment: .leading, spacing: 3) {
                            Text("AGENTS")
                                .font(.system(size: 10, weight: .bold))
                                .foregroundColor(Term.inkDim.opacity(0.6))
                                .padding(.horizontal, 12)

                            ForEach(agentRoster) { item in
                                Button {
                                    tabState.currentTab = .chat
                                    selectedAgentId = item.id
                                    Task { await activateGatewayAgent(id: item.id) }
                                    startNewChat()
                                } label: {
                                    HStack(spacing: 8) {
                                        Circle()
                                            .fill(item.color)
                                            .frame(width: 8, height: 8)
                                        Text(item.name)
                                            .font(.system(size: 12, weight: .medium))
                                            .foregroundColor(Term.ink)
                                            .lineLimit(1)
                                        Spacer()
                                        if item.unread {
                                            Circle().fill(Term.accent).frame(width: 6, height: 6)
                                        }
                                    }
                                    .padding(.horizontal, 10)
                                    .padding(.vertical, 6)
                                    .contentShape(Rectangle())
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }

                    // RECENT SESSIONS SECTION
                    VStack(alignment: .leading, spacing: 3) {
                        HStack {
                            Text("RECENT")
                                .font(.system(size: 10, weight: .bold))
                                .foregroundColor(Term.inkDim.opacity(0.6))
                            Spacer()
                            if !sessions.isEmpty {
                                Text("\(sessions.count)")
                                    .font(.system(size: 10))
                                    .foregroundColor(Term.inkDim.opacity(0.4))
                            }
                        }
                        .padding(.horizontal, 12)

                        if filteredSessions.isEmpty {
                            Text(sessionsLoaded ? "No conversations found" : "Loading chats…")
                                .font(.system(size: 11))
                                .foregroundColor(Term.inkDim.opacity(0.6))
                                .padding(.horizontal, 12)
                                .padding(.vertical, 6)
                        } else {
                            ForEach(filteredSessions) { session in
                                sessionRow(session)
                            }
                        }
                    }
                }
                .padding(.vertical, 8)
                .padding(.horizontal, 4)
            }

            Rectangle().fill(Color.white.opacity(0.05)).frame(height: 1)

            // Sidebar footer: Voice shortcut + Matthew Jenkins profile
            VStack(spacing: 6) {
                Button {
                    withAnimation(.easeInOut(duration: 0.15)) {
                        tabState.currentTab = (tabState.currentTab == .avatar ? .chat : .avatar)
                    }
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: tabState.currentTab == .avatar ? "waveform.circle.fill" : "waveform")
                            .font(.system(size: 13))
                            .foregroundColor(tabState.currentTab == .avatar ? Term.accent : Term.inkDim)
                        Text("Voice Mode")
                            .font(.system(size: 12, weight: .medium))
                            .foregroundColor(tabState.currentTab == .avatar ? Term.accent : Term.ink)
                        Spacer()
                        if tts.isSpeaking {
                            Text("Speaking")
                                .font(.system(size: 9, weight: .bold))
                                .foregroundColor(Color.green)
                        }
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background(RoundedRectangle(cornerRadius: 6).fill(tabState.currentTab == .avatar ? Color.white.opacity(0.08) : Color.clear))
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
                                .fill(agent.isConnected ? Color.green : Color.orange)
                                .frame(width: 6, height: 6)
                            Text(agent.isConnected ? "Online" : "Connecting…")
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
        .task {
            await refreshHistoryIfNeeded(force: true)
        }
    }

    private func sessionRow(_ session: SessionSummary) -> some View {
        let isSelected = session.id == chat.sessionKey && tabState.currentTab == .chat
        return Button {
            tabState.currentTab = .chat
            selectedSessionId = session.id
            Task { await chat.loadSession(session.id) }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: isSelected ? "bubble.left.fill" : "bubble.left")
                    .font(.system(size: 11))
                    .foregroundColor(isSelected ? Term.accent : Term.inkDim)
                    .frame(width: 14)

                Text(session.displayTitle)
                    .font(.system(size: 12, weight: isSelected ? .semibold : .regular))
                    .foregroundColor(isSelected ? Term.ink : Term.ink.opacity(0.85))
                    .lineLimit(1)
                    .truncationMode(.tail)

                Spacer()
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: 6)
                    .fill(isSelected ? Color.white.opacity(0.08) : Color.clear)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func projectFolderRow(name: String, icon: String, prompt: String) -> some View {
        let isExpanded = expandedProjects.contains(name)
        return VStack(alignment: .leading, spacing: 2) {
            Button {
                withAnimation(.easeInOut(duration: 0.12)) {
                    if isExpanded {
                        expandedProjects.remove(name)
                    } else {
                        expandedProjects.insert(name)
                    }
                }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                        .font(.system(size: 8, weight: .semibold))
                        .foregroundColor(Term.inkDim.opacity(0.7))
                        .frame(width: 10)

                    Image(systemName: icon)
                        .font(.system(size: 11))
                        .foregroundColor(Term.accent.opacity(0.8))
                        .frame(width: 14)

                    Text(name)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundColor(Term.ink)
                    Spacer()
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if isExpanded {
                Button {
                    tabState.currentTab = .chat
                    chat.composerText = prompt
                } label: {
                    HStack(spacing: 6) {
                        Rectangle().fill(Color.white.opacity(0.1)).frame(width: 1, height: 12)
                            .padding(.leading, 14)
                        Text("Prompt Workspace")
                            .font(.system(size: 11))
                            .foregroundColor(Term.inkDim)
                        Spacer()
                    }
                    .padding(.vertical, 3)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
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
            HStack(spacing: 6) {
                Image(systemName: "hexagon.fill")
                    .font(.system(size: 14))
                    .foregroundColor(activeAgentColor)
                Text(activeAgentName)
                    .font(.system(size: 12, weight: .semibold))
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

            Spacer()

            // Centered Nav Pills: [ Chat ] [ Avatar ] [ Work ]
            HStack(spacing: 2) {
                tabPillButton(title: "Chat", icon: "bubble.left.and.bubble.right.fill", tab: .chat)
                tabPillButton(title: "Avatar", icon: "waveform.circle.fill", tab: .avatar)
                tabPillButton(title: "Work", icon: "briefcase.fill", tab: .work)
            }
            .padding(3)
            .background(Capsule().fill(Color.white.opacity(0.05)).overlay(Capsule().stroke(Color.white.opacity(0.08), lineWidth: 1)))

            Spacer()

            Button(action: { showMonarchAuthSheet = true }) {
                Image(systemName: "creditcard")
                    .font(.system(size: 13))
                    .foregroundColor(Term.inkDim)
            }
            .buttonStyle(.plain)
            .help("Monarch Money & Finances")

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
        .padding(.vertical, 8)
        .background(Color(red: 0.05, green: 0.06, blue: 0.08))
    }

    private func tabPillButton(title: String, icon: String, tab: AppNavTab) -> some View {
        let isSelected = tabState.currentTab == tab
        return Button {
            withAnimation(.easeInOut(duration: 0.15)) {
                tabState.currentTab = tab
            }
        } label: {
            HStack(spacing: 5) {
                Image(systemName: icon)
                    .font(.system(size: 11, weight: isSelected ? .semibold : .regular))
                Text(title)
                    .font(.system(size: 12, weight: isSelected ? .semibold : .medium))
            }
            .foregroundColor(isSelected ? Term.ink : Term.inkDim)
            .padding(.horizontal, 12)
            .padding(.vertical, 5)
            .background(
                Capsule()
                    .fill(isSelected ? Color.white.opacity(0.12) : Color.clear)
            )
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
    }

    // MARK: - Empty State Hero

    private var emptyStateHero: some View {
        VStack(spacing: 28) {
            Spacer()

            VStack(spacing: 8) {
                Text("What's on your mind today?")
                    .font(.system(size: 28, weight: .semibold))
                    .foregroundColor(Term.ink)
                Text("Collaborating with \(activeAgentName)")
                    .font(.system(size: 13))
                    .foregroundColor(Term.inkDim)
            }

            // Quick suggestion chips in horizontal scroll view to prevent ANY wrapping!
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    suggestionChip(title: "Connect Monarch", icon: "creditcard.fill") {
                        showMonarchAuthSheet = true
                    }
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
                .padding(.horizontal, 2)
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
                    .lineLimit(1)
                    .fixedSize(horizontal: true, vertical: false)
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

    // MARK: - Avatar Stage View

    private var avatarStageView: some View {
        VStack(spacing: 24) {
            Spacer()

            VStack(spacing: 8) {
                Text(activeAgentName)
                    .font(.system(size: 24, weight: .bold))
                    .foregroundColor(Term.ink)

                let statusLabel: String = {
                    if tts.isSpeaking { return "Speaking aloud…" }
                    if agent.isBusy { return "Thinking…" }
                    if micOn { return "Listening for speech…" }
                    return "Ready · Tap to speak"
                }()

                Text(statusLabel)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundColor(tts.isSpeaking ? Color.green : (agent.isBusy ? Term.accent : Term.inkDim))
            }

            // High-resolution Voice Orb View
            VoiceOrbView(agent: agent)
                .frame(width: 300, height: 300)
                .background(
                    Circle()
                        .fill(
                            RadialGradient(
                                colors: [Term.accent.opacity(0.12), Color.clear],
                                center: .center,
                                startRadius: 40,
                                endRadius: 180
                            )
                        )
                )

            // Audio & Mic Controls
            HStack(spacing: 16) {
                // Mic button
                Button {
                    toggleVoice()
                    micOn = voice.isRecording
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: voice.isRecording ? "stop.fill" : "mic.fill")
                            .font(.system(size: 14))
                        Text(voice.isRecording ? "Stop Listening" : "Push to Talk")
                            .font(.system(size: 12, weight: .semibold))
                    }
                    .foregroundColor(voice.isRecording ? Color.white : Term.ink)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .background(
                        Capsule()
                            .fill(voice.isRecording ? Color.red.opacity(0.8) : Color.white.opacity(0.08))
                    )
                }
                .buttonStyle(.plain)

                // TTS Speaker Toggle
                Button {
                    tts.autoSpeakEnabled.toggle()
                    let on = tts.autoSpeakEnabled
                    Task { await agent.command("save_config", args: ["speak_replies": on]) }
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: tts.autoSpeakEnabled ? "speaker.wave.2.fill" : "speaker.slash.fill")
                            .font(.system(size: 14))
                        Text(tts.autoSpeakEnabled ? "Speaker ON" : "Muted")
                            .font(.system(size: 12, weight: .semibold))
                    }
                    .foregroundColor(tts.autoSpeakEnabled ? Color.green : Term.inkDim)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .background(
                        Capsule()
                            .fill(tts.autoSpeakEnabled ? Color.green.opacity(0.12) : Color.white.opacity(0.05))
                    )
                }
                .buttonStyle(.plain)
            }

            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Term.canvas)
    }

    // MARK: - Work Stage View (Missions & Dispatcher)

    private var workStageView: some View {
        VStack(spacing: 0) {
            // Header bar
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Autonomous Dispatcher & Missions")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundColor(Term.ink)
                    Text("Background workers, heartbeat loops, and long-running autonomous runs")
                        .font(.system(size: 11))
                        .foregroundColor(Term.inkDim)
                }
                Spacer()

                Button("Refresh") {
                    Task { await chat.refreshDispatcher() }
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
            }
            .padding(16)
            .background(Color.white.opacity(0.02))

            Rectangle().fill(Color.white.opacity(0.06)).frame(height: 1)

            ScrollView {
                VStack(spacing: 16) {
                    // Status Card
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            Circle()
                                .fill(chat.dispatcherConnected ? Color.green : Color.orange)
                                .frame(width: 8, height: 8)
                            Text(chat.dispatcherStatus)
                                .font(.system(size: 13, weight: .semibold, design: .monospaced))
                                .foregroundColor(Term.ink)
                            Spacer()
                            if let run = chat.dispatcherRun {
                                Text("Run \(run.run_id)")
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundColor(Term.inkDim)
                            }
                        }

                        if let run = chat.dispatcherRun, run.active == true {
                            HStack(spacing: 12) {
                                Button(run.status == "interrupted" ? "Reconcile" : "Stop Run") {
                                    chat.controlDispatcher(run.status == "interrupted" ? "reconcile" : "cancel")
                                }
                                .buttonStyle(.borderedProminent)
                                .tint(run.status == "interrupted" ? Term.accent : Color.red)
                                .controlSize(.small)
                            }
                        }
                    }
                    .padding(16)
                    .background(RoundedRectangle(cornerRadius: 10).fill(Term.panel).overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.06), lineWidth: 1)))

                    // Autonomous Missions Card
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Active Missions")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundColor(Term.ink)

                        HStack(spacing: 12) {
                            missionCard(
                                title: "Monarch Finance Worker",
                                subtitle: "Hourly net worth, budget & transaction audits",
                                status: "Ready",
                                icon: "creditcard.fill",
                                color: Color.green
                            ) {
                                showMonarchAuthSheet = true
                            }

                            missionCard(
                                title: "Repo Hygiene Auditor",
                                subtitle: "Git cleanliness, test suite passing, fast lint",
                                status: "Idle",
                                icon: "shield.checkerboard",
                                color: Term.accent
                            ) {
                                tabState.currentTab = .chat
                                chat.composerText = "Run repository hygiene audit"
                            }
                        }
                    }
                    .padding(16)
                    .background(RoundedRectangle(cornerRadius: 10).fill(Term.panel).overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.06), lineWidth: 1)))

                    // Dispatcher Reports
                    if !chat.dispatcherReports.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Recent Reports")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundColor(Term.ink)

                            ForEach(chat.dispatcherReports.prefix(10), id: \.run_id) { report in
                                VStack(alignment: .leading, spacing: 4) {
                                    HStack {
                                        Text(report.run_id)
                                            .font(.system(size: 12, weight: .semibold, design: .monospaced))
                                            .foregroundColor(Term.ink)
                                        Spacer()
                                        Text(report.status)
                                            .font(.system(size: 10, design: .monospaced))
                                            .foregroundColor(Term.accent)
                                    }
                                    Text(report.summary)
                                        .font(.system(size: 11))
                                        .foregroundColor(Term.inkDim)
                                        .lineLimit(2)
                                }
                                .padding(10)
                                .background(RoundedRectangle(cornerRadius: 6).fill(Color.white.opacity(0.03)))
                            }
                        }
                        .padding(16)
                        .background(RoundedRectangle(cornerRadius: 10).fill(Term.panel).overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.06), lineWidth: 1)))
                    }
                }
                .padding(16)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Term.canvas)
    }

    private func missionCard(title: String, subtitle: String, status: String, icon: String, color: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Image(systemName: icon)
                        .font(.system(size: 14))
                        .foregroundColor(color)
                    Spacer()
                    Text(status)
                        .font(.system(size: 10, weight: .bold))
                        .foregroundColor(color)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Capsule().fill(color.opacity(0.12)))
                }
                Text(title)
                    .font(.system(size: 12, weight: .bold))
                    .foregroundColor(Term.ink)
                Text(subtitle)
                    .font(.system(size: 10))
                    .foregroundColor(Term.inkDim)
                    .lineLimit(2)
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 8).fill(Color.white.opacity(0.04)).overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.06), lineWidth: 1)))
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
        case "finance", "monarch":
            chat.composerText = ""
            showMonarchAuthSheet = true
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
            // Prefer the unified `agents` array (grok_bot_shape). Fall back to
            // native+third_party slices only when `agents` is absent — never concatenate
            // all three (that triple-counted every row).
            let allLive: [GatewayClient.Agent]
            if let agents = catalog.agents, !agents.isEmpty {
                allLive = agents
            } else {
                allLive = (catalog.jaeger_native ?? []) + (catalog.third_party ?? [])
            }
            var seen = Set<String>()
            var merged: [AgentRosterItem] = []
            for a in allLive {
                guard seen.insert(a.id).inserted else { continue }
                let color: Color = a.kind == "jaeger_native"
                    ? Color(red: 0.96, green: 0.55, blue: 0.16)
                    : Color(red: 0.20, green: 0.78, blue: 0.55)
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
                if a.active == true {
                    selectedAgentId = a.id
                }
            }
            if !merged.isEmpty {
                agentRoster = merged
                gatewayAgentsAvailable = true
            } else {
                agentRoster = []
                gatewayAgentsAvailable = false
            }
        } catch {
            // Gateway down/unreachable: sessions-only — do not invent fake agent names.
            agentRoster = []
            gatewayAgentsAvailable = false
        }
    }

    /// Activate the Gateway spine agent (same contract WebUI `/api/agents/.../activate` uses).
    private func activateGatewayAgent(id: String) async {
        do {
            let activated = try await GatewayClient.fromEnvironment().activateAgent(id: id)
            selectedAgentId = activated.id
            await loadLiveAgentsFromGateway()
        } catch {
            // Keep local selection; next send still uses bridge until gateway recovers.
            NSLog("[ChatView] gateway activate failed for \(id): \(error.localizedDescription)")
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


// MARK: - Desktop projects (~/.jaeger/desktop/projects.json)

enum DesktopProjectStore {
    static let defaults: [DesktopProject] = [
        DesktopProject(
            name: "JaegerAI",
            icon: "folder.fill",
            prompt: "Review JaegerAI core daemon, tools, and interface health"
        ),
        DesktopProject(
            name: "Finances",
            icon: "chart.pie.fill",
            prompt: "Run a full financial audit on accounts and transactions"
        ),
    ]

    private static var fileURL: URL {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let state = ProcessInfo.processInfo.environment["JAEGER_STATE_DIR"]
            ?? ProcessInfo.processInfo.environment["JAEGER_HOME"]
        let root: URL
        if let state, !state.isEmpty {
            root = URL(fileURLWithPath: (state as NSString).expandingTildeInPath, isDirectory: true)
        } else {
            root = home.appendingPathComponent(".jaeger", isDirectory: true)
        }
        return root
            .appendingPathComponent("desktop", isDirectory: true)
            .appendingPathComponent("projects.json", isDirectory: false)
    }

    static func loadOrMigrate() -> [DesktopProject] {
        let url = fileURL
        let fm = FileManager.default
        do {
            try fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            if fm.fileExists(atPath: url.path) {
                let data = try Data(contentsOf: url)
                let decoded = try JSONDecoder().decode([DesktopProject].self, from: data)
                if !decoded.isEmpty { return decoded }
            }
            // Migrate defaults once
            let data = try JSONEncoder().encode(defaults)
            try data.write(to: url, options: .atomic)
            return defaults
        } catch {
            return defaults
        }
    }
}
