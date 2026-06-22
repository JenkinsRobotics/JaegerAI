//
//  MenuCard.swift
//  JaegerOS / MenuCard
//
//  The rich menu-bar dropdown — the Swift twin of the PySide6
//  ``tray/menu.py`` card: an avatar + agent name header (with a gear
//  that opens Settings) over a live agent-status row, then the quick
//  actions.  Rendered via ``MenuBarExtra(... ).menuBarExtraStyle(.window)``.
//

import AppKit
import SwiftUI

struct MenuCard: View {
    @ObservedObject var agent: AgentBridge
    @ObservedObject var tts: TTSManager
    @ObservedObject private var pill = PillBridge.shared

    /// state → ("words", dot colour), matching the PySide6 card's vocabulary.
    private var statusText: String {
        if !agent.isConnected { return "Stopped" }
        return pill.isAgentBusy ? "In deep thought…" : "Standing by"
    }
    private var statusColor: Color {
        if !agent.isConnected { return .gray }
        return pill.isAgentBusy ? .orange : .green
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            statusRow
            Divider()
            actions
        }
        .padding(14)
        .frame(width: 300)
    }

    // MARK: - sections

    private var header: some View {
        HStack(spacing: 10) {
            avatar
            VStack(alignment: .leading, spacing: 1) {
                Text(agent.status?.instance ?? AgentBridge.defaultInstanceName)
                    .font(.system(size: 14, weight: .semibold))
                Text(agent.status?.modelName ?? "Local agent")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
            Spacer()
            SettingsLink {
                Image(systemName: "gearshape")
                    .font(.system(size: 15))
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
            .help("Settings")
        }
    }

    /// The agent's face (agent.jpg), clipped to a circle. Falls back to
    /// the drawn mech mark if the asset isn't bundled.
    private var avatar: some View {
        Group {
            if let url = Bundle.module.url(forResource: "agent", withExtension: "jpg"),
               let img = NSImage(contentsOf: url) {
                Image(nsImage: img).resizable().interpolation(.high)
            } else {
                JaegerMechIcon(size: 40)
            }
        }
        .frame(width: 40, height: 40)
        .clipShape(Circle())
    }

    private var statusRow: some View {
        HStack(spacing: 10) {
            Image(systemName: "brain.head.profile")
                .font(.system(size: 16))
                .foregroundColor(.accentColor)
            VStack(alignment: .leading, spacing: 1) {
                Text("Agent Status").font(.system(size: 13, weight: .semibold))
                HStack(spacing: 6) {
                    Circle().fill(statusColor).frame(width: 8, height: 8)
                    Text(statusText).font(.system(size: 12)).foregroundStyle(.secondary)
                }
            }
            Spacer()
            Image(systemName: "chevron.right").foregroundStyle(.tertiary)
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(nsColor: .controlBackgroundColor))
        )
        .contentShape(Rectangle())
        .onTapGesture { ChatWindowController.show(agent: agent) }
    }

    private var actions: some View {
        VStack(alignment: .leading, spacing: 2) {
            if agent.isConnected {
                row("Stop Agent") { Task { await agent.disconnect() } }
            } else {
                row("Start Agent") {
                    Task {
                        do { try await agent.connect() }
                        catch { NSLog("[JaegerOS] start failed: \(error.localizedDescription)") }
                    }
                }
            }
            row("Open Chat Window") { ChatWindowController.show(agent: agent) }
            row("Quick input…  ⌥Space") { PillPanelController.toggle(agent: agent) }

            Toggle("Auto-speak replies", isOn: $tts.autoSpeakEnabled)
                .toggleStyle(.switch)
                .controlSize(.small)
                .padding(.vertical, 2)

            Divider().padding(.vertical, 2)
            row("Quit JROS", danger: true) { NSApplication.shared.terminate(nil) }
        }
    }

    @ViewBuilder
    private func row(_ label: String, danger: Bool = false,
                     _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(label)
                .font(.system(size: 13))
                .foregroundColor(danger ? .red : .primary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .padding(.vertical, 3)
    }
}
