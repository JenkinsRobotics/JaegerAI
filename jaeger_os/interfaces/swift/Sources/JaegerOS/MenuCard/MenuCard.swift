//
//  MenuCard.swift
//  JaegerOS / MenuCard
//
//  The rich menu-bar dropdown — the Swift twin of the PySide6
//  ``tray/menu.py`` card. Header: the ACTIVE CHARACTER's avatar + name over a
//  live status line (● + words). Then an action bar: chat · agent, with
//  quick-input on the right. Settings + power live in the header.
//

import AppKit
import SwiftUI

struct MenuCard: View {
    @ObservedObject var agent: AgentBridge
    @ObservedObject var tts: TTSManager
    @ObservedObject private var pill = PillBridge.shared

    /// Display name = the active character, else instance, else a default.
    private var displayName: String {
        agent.status?.character ?? agent.status?.instance ?? AgentBridge.defaultInstanceName
    }

    /// state → words, matching the PySide6 card's vocabulary.
    private var statusText: String {
        if !agent.isConnected { return "Offline" }
        return pill.isAgentBusy ? "In deep thought…" : "Standing by"
    }
    private var statusColor: Color {
        if !agent.isConnected { return .gray }
        return pill.isAgentBusy ? .orange : .green
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            actionBar
        }
        .padding(14)
        .frame(width: 300)
    }

    // MARK: - header (avatar · name+status · settings · power)

    private var header: some View {
        HStack(spacing: 10) {
            avatar
            VStack(alignment: .leading, spacing: 2) {
                Text(displayName)
                    .font(.system(size: 14, weight: .semibold))
                    .lineLimit(1)
                HStack(spacing: 6) {
                    Circle().fill(statusColor).frame(width: 8, height: 8)
                    Text(statusText).font(.system(size: 12)).foregroundStyle(.secondary)
                }
            }
            Spacer()
            SettingsLink {
                Image(systemName: "gearshape")
                    .font(.system(size: 15)).foregroundStyle(.secondary)
            }
            .buttonStyle(.plain).help("Settings")
            powerMenu
        }
    }

    /// The active character's face, clipped to a circle. Falls back to the
    /// bundled agent image, then the drawn mech mark.
    private var avatar: some View {
        Group {
            if let path = agent.status?.iconPath, let img = NSImage(contentsOfFile: path) {
                Image(nsImage: img).resizable().interpolation(.high)
            } else if let url = Bundle.module.url(forResource: "agent", withExtension: "jpg"),
                      let img = NSImage(contentsOf: url) {
                Image(nsImage: img).resizable().interpolation(.high)
            } else {
                JaegerMechIcon(size: 40)
            }
        }
        .frame(width: 40, height: 40).clipShape(Circle())
    }

    private var powerMenu: some View {
        Menu {
            if agent.isConnected {
                Button("Stop Agent") { Task { await agent.disconnect() } }
            } else {
                Button("Start Agent") { Task { await agent.tryConnect() } }
            }
            Button("Restart") { relaunch() }
            Divider()
            Button("Quit JROS", role: .destructive) { NSApplication.shared.terminate(nil) }
        } label: {
            Image(systemName: "power").font(.system(size: 15)).foregroundStyle(.secondary)
        }
        .menuStyle(.borderlessButton).fixedSize().help("Agent · restart · quit")
    }

    // MARK: - action bar (chat · agent · quick-input)

    private var actionBar: some View {
        HStack(spacing: 8) {
            iconButton("bubble.left", "Open chat window") {
                ChatWindowController.show(agent: agent)
            }
            iconButton("person.crop.circle", "Agent — avatar + chat") {
                AvatarChatWindowController.show(agent: agent)
            }
            Spacer()
            iconButton("bolt.fill", "Quick input") {
                PillPanelController.toggle(agent: agent)
            }
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 10)
            .fill(Color(nsColor: .controlBackgroundColor)))
    }

    private func iconButton(_ symbol: String, _ help: String,
                            _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 16))
                .foregroundStyle(.secondary)
                .frame(width: 30, height: 26)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain).help(help)
    }

    private func relaunch() {
        if let path = Bundle.main.executablePath {
            let proc = Process()
            proc.executableURL = URL(fileURLWithPath: path)
            try? proc.run()
        }
        NSApplication.shared.terminate(nil)
    }
}
