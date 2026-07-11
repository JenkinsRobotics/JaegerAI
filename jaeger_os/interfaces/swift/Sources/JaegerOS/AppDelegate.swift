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

        SplashWindowController.shared.show()

        // Bring the native app online behind the splash. The menu-bar app still
        // exists immediately, but expensive readiness work is surfaced here so
        // the operator sees what is happening instead of waiting on a blank UI.
        Task { @MainActor in
            let splash = SplashWindowController.shared

            splash.start("interface", "Interface core",
                         detail: "Preparing menu bar, resources, and splash surface",
                         progress: 0.12)
            splash.complete("interface", detail: "Native shell ready", progress: 0.22)

            // Try to connect to the agent right away.  ``tryConnect``
            // logs + records lastError on failure instead of throwing —
            // a missing bridge is the expected state for an operator
            // who has not started the agent yet, not an exception.
            splash.start("bridge", "Agent bridge",
                         detail: "Starting JROS bridge and waiting for model readiness",
                         progress: 0.32)
            await AgentBridge.shared.tryConnect()
            if AgentBridge.shared.isConnected {
                // Fast-ready: the transport connects in ~0.5s while the
                // model (gemma + whisper + kokoro warm) loads BEHIND it.
                // The splash must ride the real lifecycle — hold here
                // until agent_state leaves ``booting`` so it can't
                // dismiss over a still-loading agent.
                splash.complete("bridge", detail: "Bridge connected",
                                progress: 0.45)
                splash.start("model", "Agent model",
                             detail: "Loading model + voice stack "
                                     + "(the long pole)…",
                             progress: 0.5)
                let modelBootStarted = Date()
                while AgentBridge.shared.isAgentBooting {
                    try? await Task.sleep(for: .milliseconds(250))
                    let elapsed = Date().timeIntervalSince(modelBootStarted)
                    let estimate = min(0.66, 0.50 + (elapsed / 45.0 * 0.16))
                    splash.advance("model",
                                   detail: "Loading model + voice stack…",
                                   progress: estimate)
                }
                if case .failed(let why) = AgentBridge.shared.agentState {
                    splash.fail("model", detail: why, progress: 0.68)
                } else {
                    let model = AgentBridge.shared.status?.modelName
                        ?? "model online"
                    splash.complete("model", detail: model, progress: 0.68)
                }
                splash.start("settings", "Settings cache",
                             detail: "Preloading characters, app config, and permissions",
                             progress: 0.74)
                await SettingsStore.shared.preload()
                splash.complete("settings", detail: "Settings ready", progress: 0.88)
            } else {
                let error = AgentBridge.shared.lastError ?? "Agent bridge unavailable"
                splash.fail("bridge", detail: error, progress: 0.68)
            }

            // ⌥Space — global hotkey toggles the floating pill launcher.
            // Routes through the same controller as the menu-bar item, so
            // both surfaces share one panel and one show/hide state
            // machine.  Carbon's RegisterEventHotKey requires no
            // Accessibility permission (unlike NSEvent global monitors)
            // so first-run UX has no permission wall.
            splash.start("hotkey", "Operator controls",
                         detail: "Registering Option-Space launcher",
                         progress: 0.92)
            PillHotkey.shared.register {
                PillPanelController.toggle(agent: AgentBridge.shared)
            }
            splash.complete("hotkey", detail: "Operator controls ready", progress: 0.97)

            await splash.finish(AgentBridge.shared.isConnected
                                ? "All systems online"
                                : "Offline shell ready")
        }

        // In-app updates (0.8): a silent check on launch, then every ~6h —
        // matches the Python-side cache TTL (version_check.
        // cached_update_status), so this loop is cheap even at that
        // cadence: most calls just replay the cached "latest" without a
        // network round-trip. Lights up the menu-bar dot (JaegerOSApp) and
        // the MenuCard/Settings Updates row (SettingsStore.updateStatus is
        // the shared @Published source both read) — never a modal.
        Task { @MainActor in
            while !Task.isCancelled {
                _ = await SettingsStore.shared.checkForUpdates()
                try? await Task.sleep(for: .seconds(24 * 3600))
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

    /// The app's ONE exit door (Quit from the tray card, Cmd-Q): hold
    /// termination until the core shuts down orderly — model freed,
    /// ``bye`` emitted, clean exit code — then let the app go. Bounded by
    /// ``quitGracefully``'s grace period, so quit can never hang.
    func applicationShouldTerminate(
        _ sender: NSApplication
    ) -> NSApplication.TerminateReply {
        if shutdownStarted { return .terminateNow }
        shutdownStarted = true
        Task { @MainActor in
            await AgentBridge.shared.shutdownForQuit()
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }

    private var shutdownStarted = false
}
