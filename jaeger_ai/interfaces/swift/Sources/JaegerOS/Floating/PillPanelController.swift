//
//  PillPanelController.swift
//  JaegerOS / Floating
//
//  Singleton that owns the ``PillPanel`` lifecycle.  Mirrors
//  ``ChatWindowController.shared`` so the two surfaces look the same
//  from the menu-bar's perspective:
//
//      ChatWindowController.show(agent: agent)        // chat
//      PillPanelController.toggle(agent: agent)        // floating pill
//
//  The controller handles:
//
//    - one-time NSPanel creation (lazy; reused on subsequent toggles)
//    - centred-bottom positioning, 100 px above the active screen's
//      bottom edge (same offset Lilith used so muscle memory carries)
//    - auto-dismiss on key-resign (PyQt6 ``focusOutEvent`` analogue)
//    - send routing via ``Notification.Name.pillSubmit`` — the chat
//      window observes it, raises itself, submits to the agent.
//      Decoupled on purpose so the pill doesn't have to know the
//      ChatViewModel's send signature.
//

import AppKit
import SwiftUI

@MainActor
final class PillPanelController: NSObject {

    static let shared = PillPanelController()

    private var panel: PillPanel?
    private var agent: AgentBridge?
    private var resignObserver: NSObjectProtocol?

    private override init() { super.init() }

    // MARK: - Public API

    /// Toggle the pill: hide it if visible, show + focus it otherwise.
    /// Bound to both the menu-bar "Open Pill Launcher" item and the
    /// ⌥Space global hotkey.
    static func toggle(agent: AgentBridge) {
        shared.toggleInternal(agent: agent)
    }

    /// Force-hide (used by the controller's own dismiss callback +
    /// the Esc key path inside the panel).
    static func hide() {
        shared.panel?.orderOut(nil)
    }

    // MARK: - Internals

    private func toggleInternal(agent: AgentBridge) {
        self.agent = agent
        let panel = ensurePanel(agent: agent)
        if panel.isVisible {
            panel.orderOut(nil)
            return
        }
        positionBottomCenter(panel: panel)
        // Bridge token bump → PillView observes and refocuses the
        // TextField even when the panel is being reused (the SwiftUI
        // ``.onAppear`` doesn't fire across reveals of a panel that
        // was just ordered out).
        PillBridge.shared.revealToken = UUID()
        NSApp.activate(ignoringOtherApps: false)
        panel.makeKeyAndOrderFront(nil)
    }

    private func ensurePanel(agent: AgentBridge) -> PillPanel {
        if let panel { return panel }
        let actions = PillActions(
            submit: { [weak self] text in
                self?.handleSubmit(text: text)
            },
            dismiss: { [weak self] in
                self?.panel?.orderOut(nil)
            },
            openChatWindow: { [weak self] in
                guard let self, let agent = self.agent else { return }
                self.panel?.orderOut(nil)
                ChatWindowController.show(agent: agent)
            },
            notImplemented: { what in
                NSLog("[JaegerOS][pill] \(what) — not implemented yet")
            }
        )
        let hosting = NSHostingController(
            rootView: PillView(actions: actions)
                .environmentObject(agent)
                .environmentObject(PillBridge.shared)
        )
        // The panel's content rect is 720 × 160 (slightly taller than
        // the Lilith 720 × 140 so the bottom row's pills don't crowd
        // the rounded corner).
        let newPanel = PillPanel()
        newPanel.contentViewController = hosting
        // Pin the frame RIGHT AFTER the hosting assignment: AppKit derives
        // the window size from SwiftUI's fitting size asynchronously, so
        // positioning on first summon could measure a stale width — the
        // pill then hangs off-center (left edge at midX). Explicit size +
        // an immediate layout keeps every centre computation truthful.
        newPanel.setContentSize(NSSize(width: 720, height: 160))
        newPanel.layoutIfNeeded()

        // Auto-dismiss on key-resign — operator clicks back to whatever
        // they were doing → pill goes away.  Mirrors PyQt6
        // ``focusOutEvent``.
        //
        // Singleton-lifetime caveat: ``resignObserver`` is stored on
        // the singleton and never removed, because the singleton
        // outlives any panel teardown.  If we ever add a path that
        // destroys the panel (e.g. backend swap), we MUST also remove
        // this observer first — see ``invalidatePanel`` below for the
        // teardown path that handles it.
        resignObserver = NotificationCenter.default.addObserver(
            forName: NSWindow.didResignKeyNotification,
            object: newPanel,
            queue: .main
        ) { _ in
            Task { @MainActor in
                PillPanelController.shared.panel?.orderOut(nil)
            }
        }

        panel = newPanel
        return newPanel
    }

    /// Teardown hook — currently unused by any production path, but
    /// exposed so future code that recreates the panel (display swap,
    /// backend reset, …) doesn't leak ``resignObserver``.
    func invalidatePanel() {
        if let resignObserver {
            NotificationCenter.default.removeObserver(resignObserver)
            self.resignObserver = nil
        }
        panel?.orderOut(nil)
        panel = nil
    }

    private func positionBottomCenter(panel: PillPanel) {
        // Prefer the screen containing whatever the operator was just
        // interacting with — the key window's screen, then the mouse-
        // location screen, then the primary screen — so a pill summoned
        // on the secondary monitor doesn't fly to the main display.
        let screen: NSScreen
        if let keyScreen = NSApp.keyWindow?.screen {
            screen = keyScreen
        } else if let mouseScreen = NSScreen.screens.first(where: {
            $0.frame.contains(NSEvent.mouseLocation)
        }) {
            screen = mouseScreen
        } else if let primary = NSScreen.main ?? NSScreen.screens.first {
            screen = primary
        } else {
            return  // no displays attached — punt
        }

        let visible = screen.visibleFrame
        panel.layoutIfNeeded()          // never measure a pre-layout frame
        let size = panel.frame.size

        // Centre, then clamp inside visibleFrame so a narrow display
        // (or a 720pt panel against a 700pt visible width — happens
        // when the menu bar + Dock subtract enough) can't leave the
        // panel partially off-screen.
        let centeredX = visible.midX - size.width / 2
        let clampedX = max(visible.minX,
                           min(centeredX, visible.maxX - size.width))
        // 120pt above the visible bottom edge — matches the Lilith
        // PyQt6 offset.  Clamp the same way so a sub-300pt visible
        // height (rare but possible with some Spaces / fullscreen
        // configurations) doesn't push the pill out the top.
        let preferredY = visible.minY + 120
        let clampedY = max(visible.minY,
                           min(preferredY, visible.maxY - size.height))

        panel.setFrameOrigin(NSPoint(x: clampedX, y: clampedY))
    }

    private func handleSubmit(text: String) {
        // Open / raise the chat window first so the operator sees the
        // submitted prompt land somewhere.  Then drop the text into
        // PillBridge — ChatView reads it via ``.onChange`` AND drains
        // it in ``.onAppear``, covering both "view already mounted"
        // and "view mounting now (cold launch)" paths.  Replaces the
        // earlier NotificationCenter approach, which raced on cold
        // launch because the ``.onReceive`` subscription wasn't
        // installed until after the first layout pass.
        if let agent { ChatWindowController.show(agent: agent) }
        PillBridge.shared.pendingPrompt = text
        panel?.orderOut(nil)
    }
}
