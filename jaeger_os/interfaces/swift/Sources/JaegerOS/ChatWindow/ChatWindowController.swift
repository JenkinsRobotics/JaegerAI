//
//  ChatWindowController.swift
//  JaegerOS / ChatWindow
//
//  Bridge between AppKit window management and SwiftUI view content.
//
//  Why AppKit + SwiftUI instead of a pure SwiftUI ``Window`` scene:
//  the SwiftUI ``Window`` API requires modelling the window as a
//  declarative scene that the operator opens via ``openWindow``.  In
//  a MenuBarExtra-only accessory app, plumbing ``openWindow`` through
//  the menu's content closure is awkward and the resulting window
//  doesn't activate the app correctly when the app is .accessory.
//
//  A tiny NSWindowController wrapping ``NSHostingController(rootView:)``
//  sidesteps both problems: we get full NSWindow lifecycle control,
//  the chat window can be raised + focused without making the whole
//  app .regular, and SwiftUI still owns every pixel inside.
//

import AppKit
import Combine
import SwiftUI

@MainActor
final class ChatWindowController {

    /// Singleton — one chat window per app session.  Clicking "Open
    /// Chat" again raises the existing window instead of spawning a
    /// duplicate (same UX the Lilith PyQt6 pill + chat used).
    static let shared = ChatWindowController()

    private var window: NSWindow?
    private var titleSub: AnyCancellable?

    private init() {}

    /// Window title leads with the AGENT's name (identity.yaml — the robot
    /// the operator named), not the character it's playing: "Jaeger — Ted".
    /// Falls back to the character until the identity query answers.
    private static func title(for status: AgentStatus?) -> String {
        if let name = status?.displayName { return "Jaeger — \(name)" }
        return "Jaeger"
    }

    /// Show (or raise) the chat window, wiring the SwiftUI ``ChatView``
    /// to the shared ``AgentBridge``.
    static func show(agent: AgentBridge) {
        shared.showOrRaise(agent: agent)
    }

    private func showOrRaise(agent: AgentBridge) {
        if let window {
            NSApp.activate(ignoringOtherApps: true)
            window.makeKeyAndOrderFront(nil)
            return
        }

        let view = ChatView(agent: agent)
            .environmentObject(agent)
        let hosting = NSHostingController(rootView: view)

        let win = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 520, height: 600),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        win.title = Self.title(for: agent.status)
        win.titlebarAppearsTransparent = true
        // The content is a hard dark terminal canvas regardless of the
        // system theme — pin the WINDOW to dark too, or under the light
        // appearance the titlebar draws near-black title text over the
        // dark canvas ("Jaeger — …" was unreadable) and system-coloured
        // controls collapse the same way.
        win.appearance = NSAppearance(named: .darkAqua)
        win.backgroundColor = NSColor(
            red: 0.043, green: 0.055, blue: 0.078, alpha: 1.0) // Term.canvas
        win.isReleasedWhenClosed = false
        win.contentViewController = hosting
        win.center()
        win.setFrameAutosaveName("JaegerChatWindow")
        win.minSize = NSSize(width: 460, height: 480)

        window = win
        // Re-title live on character switches (status is @Published).
        titleSub = agent.$status.sink { [weak win] status in
            win?.title = Self.title(for: status)
        }
        NSApp.activate(ignoringOtherApps: true)
        win.makeKeyAndOrderFront(nil)
    }
}
