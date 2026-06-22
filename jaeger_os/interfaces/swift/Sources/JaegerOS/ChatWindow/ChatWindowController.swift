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
import SwiftUI

@MainActor
final class ChatWindowController {

    /// Singleton — one chat window per app session.  Clicking "Open
    /// Chat" again raises the existing window instead of spawning a
    /// duplicate (same UX the Lilith PyQt6 pill + chat used).
    static let shared = ChatWindowController()

    private var window: NSWindow?

    private init() {}

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
        win.title = "Jaeger"
        win.titlebarAppearsTransparent = true
        win.isReleasedWhenClosed = false
        win.contentViewController = hosting
        win.center()
        win.setFrameAutosaveName("JaegerChatWindow")
        win.minSize = NSSize(width: 460, height: 480)

        window = win
        NSApp.activate(ignoringOtherApps: true)
        win.makeKeyAndOrderFront(nil)
    }
}
