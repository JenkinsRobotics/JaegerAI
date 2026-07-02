//
//  AvatarWindows.swift
//  JaegerOS / Avatar
//
//  Two surfaces, Swift twins of the PySide6 avatar windows:
//    * AvatarWindowController      — the orb on its own ("agent window")
//    * AvatarChatWindowController  — orb (left) + chat (right) + mic/speaker
//

import AppKit
import SwiftUI

// MARK: - agent window (orb only)

@MainActor
final class AvatarWindowController {
    static let shared = AvatarWindowController()
    private var window: NSWindow?

    static func show(agent: AgentBridge) { shared.present(agent: agent) }

    private func present(agent: AgentBridge) {
        if let window {
            NSApp.activate(ignoringOtherApps: true)
            window.makeKeyAndOrderFront(nil)
            return
        }
        let view = VoiceOrbView(agent: agent)
            .padding(20)
            .frame(minWidth: 320, minHeight: 380)
            .background(Color(red: 0.04, green: 0.05, blue: 0.06))
        let win = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 360, height: 420),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered, defer: false)
        win.title = "Jaeger — Avatar"
        win.titlebarAppearsTransparent = true
        win.isReleasedWhenClosed = false
        win.contentViewController = NSHostingController(rootView: view)
        win.center()
        window = win
        NSApp.activate(ignoringOtherApps: true)
        win.makeKeyAndOrderFront(nil)
    }
}

// MARK: - agent + chat window

@MainActor
final class AvatarChatWindowController {
    static let shared = AvatarChatWindowController()
    private var window: NSWindow?

    static func show(agent: AgentBridge) { shared.present(agent: agent) }

    private func present(agent: AgentBridge) {
        if let window {
            NSApp.activate(ignoringOtherApps: true)
            window.makeKeyAndOrderFront(nil)
            return
        }
        let view = AvatarChatView(agent: agent).environmentObject(agent)
        let win = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1040, height: 640),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered, defer: false)
        win.title = "Jaeger — Avatar + Chat"
        win.titlebarAppearsTransparent = true
        win.isReleasedWhenClosed = false
        win.contentViewController = NSHostingController(rootView: view)
        win.center()
        win.minSize = NSSize(width: 820, height: 480)
        window = win
        NSApp.activate(ignoringOtherApps: true)
        win.makeKeyAndOrderFront(nil)
    }
}

private struct AvatarChatView: View {
    @ObservedObject var agent: AgentBridge
    @ObservedObject private var tts = TTSManager.shared
    @State private var micOn = false     // chat-mode default: mic off

    private let canvas = Color(red: 0.043, green: 0.055, blue: 0.078)
    private let panel = Color(red: 0.075, green: 0.090, blue: 0.122)

    var body: some View {
        HSplitView {
            VStack(spacing: 10) {
                Text("AVATAR")
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                VoiceOrbView(agent: agent)
                controls
            }
            .padding(16)
            .frame(minWidth: 340)
            .background(panel)

            ChatView(agent: agent)
                .environmentObject(agent)
                .frame(minWidth: 620)
        }
        .background(canvas)
    }

    private var controls: some View {
        HStack(spacing: 14) {
            Spacer()
            toggle(on: micOn, onSymbol: "mic.fill", offSymbol: "mic.slash",
                   help: micOn ? "Mic on — voice input" : "Mic off") {
                micOn.toggle()   // voice-input loop lands with the STT wiring
            }
            toggle(on: tts.autoSpeakEnabled, onSymbol: "speaker.wave.2.fill",
                   offSymbol: "speaker.slash", help: tts.autoSpeakEnabled ? "Speaker on" : "Speaker off") {
                tts.autoSpeakEnabled.toggle()
            }
            Spacer()
        }
    }

    private func toggle(on: Bool, onSymbol: String, offSymbol: String, help: String,
                        _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: on ? onSymbol : offSymbol)
                .font(.system(size: 18))
                .foregroundStyle(on ? Color.green : Color.secondary)
                .frame(width: 40, height: 36)
                .background(RoundedRectangle(cornerRadius: 18)
                    .fill(on ? Color.green.opacity(0.18) : Color.white.opacity(0.05)))
        }
        .buttonStyle(.plain).help(help)
    }
}
