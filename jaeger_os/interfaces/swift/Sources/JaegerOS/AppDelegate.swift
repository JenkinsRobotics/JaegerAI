//
//  AppDelegate.swift
//  JaegerOS
//
//  Tiny shim that sets the activation policy + tears down cleanly on
//  termination. Most of the app lifecycle is owned by the SwiftUI App
//  scene; this delegate exists for the bits that have to happen before
//  the first scene activates.
//

import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    /// Called once, before any scene materialises.
    func applicationDidFinishLaunching(_ notification: Notification) {
        // ``.accessory`` makes JaegerOS a menu-bar-only app: no Dock
        // icon, no Cmd-Tab presence. Without this, an SPM-built
        // executable launched with no Info.plist defaults to ``.regular``
        // and the app vanishes the moment its (nonexistent) main window
        // would close.
        NSApp.setActivationPolicy(.accessory)
        NSLog("[JaegerOS] app launched, activation policy = .accessory")

        // Try to connect to the agent right away.  ``tryConnect``
        // logs + records lastError on failure instead of throwing —
        // a missing socket file is the expected state for an operator
        // who hasn't started the agent yet, not an exception.
        Task { @MainActor in
            await AgentBridge.shared.tryConnect()
        }

        // ⌥Space — global hotkey toggles the floating pill launcher.
        // Routes through the same controller as the menu-bar item, so
        // both surfaces share one panel and one show/hide state
        // machine.  Carbon's RegisterEventHotKey requires no
        // Accessibility permission (unlike NSEvent global monitors)
        // so first-run UX has no permission wall.
        Task { @MainActor in
            PillHotkey.shared.register {
                PillPanelController.toggle(agent: AgentBridge.shared)
            }
        }
    }

    /// Best-effort Carbon hotkey unregister on shutdown.  Honest
    /// about the limitation: ``applicationWillTerminate`` is followed
    /// by process exit nearly immediately, so the ``Task { @MainActor }``
    /// we dispatch here usually doesn't get to run before the OS
    /// reclaims everything.  We still file the request because
    /// shutdown is sometimes ordered enough (graceful Quit from the
    /// menu) for it to actually run — and unregistering is cheap +
    /// idempotent — but the system reclaiming our hotkey on process
    /// exit is what's actually doing the work in the common case.
    func applicationWillTerminate(_ notification: Notification) {
        Task { @MainActor in
            PillHotkey.shared.unregister()
        }
    }

    /// Quit cleanly when the last window closes — irrelevant for our
    /// menu-bar-only app, but keeps semantics tidy for any future
    /// window-bearing modes (e.g. when the chat window is the only
    /// surface and the operator closes it intentionally).
    func applicationShouldTerminateAfterLastWindowClosed(
        _ sender: NSApplication
    ) -> Bool {
        // We're a menu-bar app. Closing a window should NOT quit us.
        return false
    }
}
