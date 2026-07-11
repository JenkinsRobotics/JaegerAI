//
//  MenuCard.swift
//  JaegerOS / MenuCard
//
//  The rich menu-bar dropdown — the Swift twin of the PySide6
//  ``tray/menu.py`` card. Header: the AGENT's avatar + name (identity.yaml,
//  not the character) over a live status line (● + words). Then an action bar: chat · agent, with
//  quick-input on the right. Settings + power live in the header.
//

import AppKit
import SwiftUI

struct MenuCard: View {
    @ObservedObject var agent: AgentBridge
    @ObservedObject var tts: TTSManager
    @ObservedObject private var settings = SettingsStore.shared

    /// Display name = the AGENT's name (identity.yaml), never the character —
    /// the character is only the persona it's playing. Falls back to the
    /// instance while the identity query is in flight, then the default.
    private var displayName: String {
        agent.status?.displayName ?? agent.status?.instance ?? AgentBridge.defaultInstanceName
    }

    /// One derived status for the header row — words + dot colour matching
    /// the PySide6 card's vocabulary (``tray/menu.py`` ``_STATE_DISPLAY``),
    /// extended with the transport truth the Qt card never had: connecting,
    /// warming up (fast-ready handshake before the model loads), and the
    /// failed/terminated reasons off the connection state machine.
    private var status: (text: String, color: Color, detail: String?) {
        switch agent.state {
        case .disconnected:
            return ("Offline", .gray, nil)
        case .connecting:
            return ("Connecting…", .orange, nil)
        case .failed(let m), .terminated(let m):
            return ("Something went wrong", .red, m)
        case .ready:
            if case .failed(let reason) = agent.agentState {
                return ("Something went wrong", .red, reason)
            }
            if agent.isAgentBooting { return ("Warming up…", .orange, nil) }
            if agent.isBusy { return ("In deep thought…", .orange, nil) }
            return ("Standing by", .green, nil)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            actionBar
        }
        .padding(14)
        .frame(width: 300)
        // Fresh identity every open — a character switched from another
        // surface (or edited on disk) shows up the next time the card drops.
        .task { await agent.refreshIdentity() }
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
                    Circle().fill(status.color).frame(width: 8, height: 8)
                    Text(status.text).font(.system(size: 12)).foregroundStyle(.secondary)
                }
                .help(status.detail ?? status.text)
            }
            Spacer()
            if settings.updateStatus?.available == true {
                SettingsLink {
                    HStack(spacing: 4) {
                        Circle().fill(Color(red: 1.0, green: 0.35, blue: 0.35))
                            .frame(width: 6, height: 6)
                        Text("Update").font(.system(size: 11, weight: .semibold))
                    }
                    .foregroundStyle(HUD.accent)
                }
                .buttonStyle(.plain)
                .help("v\(settings.updateStatus?.latest ?? "?") is available — opens Settings → App Settings → Updates")
            }
            SettingsLink {
                Image(systemName: "gearshape")
                    .font(.system(size: 15)).foregroundStyle(.secondary)
            }
            .buttonStyle(.plain).help("Settings")
            powerMenu
        }
    }

    /// The agent's effective avatar (instance profile picture if set, else the
    /// active character's card), clipped to a circle. Falls back to the bundled
    /// agent image, then the drawn mech mark.
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
