//
//  JaegerOSApp.swift
//  JaegerOS
//
//  Entry point for the JROS desktop app.
//
//  Week 0 scaffold (2026-06-02): a MenuBarExtra-only app that
//  appears in the system menu bar and exposes a Quit menu item.
//  No window, no agent connection, no chat yet — just the
//  foundation the rest of 0.3.0 builds on.
//
//  Week 1 adds the Unix-socket agent client.
//  Week 2 adds the SwiftUI chat window.
//  Week 3 adds the pill launcher + Option+Space hotkey.
//  Week 4-5 add AVAudioEngine voice loop + CoreML Whisper.
//

import AppKit
import SwiftUI

@main
struct JaegerOSApp: App {
    /// AppDelegate runs ``applicationDidFinishLaunching`` before any
    /// scenes are activated. Use it to mark the app as a menu-bar
    /// accessory so it stays alive without a Dock icon — necessary
    /// for SwiftPM-built apps that ship without a real Info.plist.
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    /// The Unix-socket agent client (Week 1).  Owns the connection,
    /// surfaces ``isConnected`` for the menu-bar icon swap, ``status``
    /// for the dropdown, and an event stream for future chat fanout.
    /// Backed by ``AgentBridge.shared`` so the AppDelegate's launch hook
    /// and SwiftUI's view tree are looking at the same instance.
    @StateObject private var agent = AgentBridge.shared

    /// Shared TTS manager — the menu surfaces an auto-speak toggle
    /// and a "Stop Speaking" item when audio is active.
    @StateObject private var tts = TTSManager.shared

    /// Backs the menu-bar "update available" dot (0.8) — the same store
    /// the Settings HUD's Updates row reads, so one background poll
    /// (``AppDelegate``, launch + ~6h) lights up both surfaces at once.
    @StateObject private var settingsStore = SettingsStore.shared

    /// Derived from ``agent.isConnected`` — the menu-bar icon swap
    /// flag.  We keep it explicit (not a computed property) so the
    /// SwiftUI view tree's binding is dead simple.
    private var agentState: AgentLinkState {
        agent.isConnected ? .connected : .disconnected
    }

    var body: some Scene {
        // SwiftUI's MenuBarExtra (macOS 13+) — declarative menu-bar
        // icon. Replaces the rumps-on-PyObjC tray we deleted in 0.2.6.
        // Label is the JROS J mark — the same artwork the 0.2.x tray
        // used. ``jaeger_icon_22.png`` is 44×44 (22pt @ 2x retina),
        // exactly what the menu bar expects. The mech head SwiftUI
        // Shape in JaegerMechIcon.swift stays around for in-app
        // branding (chat window header, About panel, etc.).
        MenuBarExtra {
            // The rich dropdown card (avatar · name · live status ·
            // actions · gear→Settings) — the Swift twin of the PySide6
            // ``tray/menu.py`` card.
            MenuCard(agent: agent, tts: tts)
        } label: {
            // Two-state icon: colored J when the agent is up, greyed
            // J when it's down or unreachable. Same UX the 0.2.x tray
            // had — operators glance at the menu bar and know whether
            // the agent is alive without opening anything.
            //
            // Resources loaded via Bundle.module.url(...) — Image(_:bundle:)
            // expects an asset catalog and silently renders nothing for
            // loose PNGs sitting under Resources/.
            ZStack(alignment: .topTrailing) {
                if let icon = Self.icon(for: agentState) {
                    Image(nsImage: icon)
                        .resizable()
                        .interpolation(.high)
                        .aspectRatio(contentMode: .fit)
                        // 18pt — the AppKit standard menu-bar item height
                        // (NSStatusItem default, what Ollama / Raycast /
                        // Alfred all settle on).  The source PNG ships at
                        // 44×44 (22pt @2x); ``loadIcon`` sets
                        // ``image.size = 18`` so SwiftUI renders against the
                        // PNG's native pixels without a chain of resamples.
                        //
                        // 0.3.0: was 14pt, which downsampled the J disc to
                        // ~64% of menu-bar standard and read visually
                        // smaller than its neighbours.  Lilith's PyQt6
                        // ``QSystemTrayIcon(QIcon)`` handles menu-bar
                        // sizing automatically; AppKit needs the explicit
                        // hint.
                        .frame(width: 18, height: 18)
                } else {
                    // Fallback so we NEVER have an empty label.  If we hit
                    // this, the resource bundle didn't pick up the PNGs —
                    // the SwiftUI Shape stays visible at the same 18pt so
                    // the menu remains clickable and matches neighbour
                    // weight.
                    JaegerMechIcon(size: 18)
                }
                // Update-available dot (0.8) — subtle, no modal nagging.
                // Backed by the SAME cached check_update poll the Updates
                // row reads (SettingsStore.updateStatus), so the dot and
                // the row never disagree.
                if settingsStore.updateStatus?.available == true {
                    Circle()
                        .fill(Color(red: 1.0, green: 0.35, blue: 0.35))
                        .frame(width: 6, height: 6)
                        .offset(x: 2, y: -1)
                }
            }
        }
        .menuBarExtraStyle(.window)   // render the SwiftUI card, not a text menu

        // The Settings/Preferences window (⌘, or the card's gear).
        Settings {
            SettingsView()
        }
    }

    /// Pick the right NSImage for the current agent state. Both icons
    /// are loaded once at app startup and reused.
    private static func icon(for state: AgentLinkState) -> NSImage? {
        switch state {
        case .connected: return runningIcon
        case .disconnected: return offIcon
        }
    }

    private static let runningIcon: NSImage? =
        loadIcon(name: "jaeger_icon_22")
    private static let offIcon: NSImage? =
        loadIcon(name: "jaeger_icon_off_22")

    /// Load a PNG from the SwiftPM resource bundle and size it for the
    /// menu bar.  Returns nil + logs to stderr if the resource isn't
    /// where we expect.
    ///
    /// The PNGs ship at 44×44 (22pt @2x).  We set ``image.size`` to
    /// 18×18 here so SwiftUI's ``Image(nsImage:).resizable()`` walks
    /// from a known target size instead of starting from the raw 44px
    /// representation — the latter visibly aliased the J disc.  This
    /// mirrors how Lilith's ``QSystemTrayIcon(QIcon)`` handles
    /// menu-bar sizing transparently in Qt.
    private static func loadIcon(name: String) -> NSImage? {
        guard let url = Bundle.module.url(forResource: name,
                                          withExtension: "png") else {
            NSLog("[JaegerOS] icon load FAILED — \(name).png not found "
                  + "in Bundle.module (\(Bundle.module.bundlePath))")
            return nil
        }
        guard let img = NSImage(contentsOf: url) else {
            NSLog("[JaegerOS] icon load FAILED — NSImage(contentsOf:) "
                  + "returned nil for \(url.path)")
            return nil
        }
        img.size = NSSize(width: 18, height: 18)
        NSLog("[JaegerOS] icon loaded: \(name).png (size=18×18pt)")
        return img
    }
}

/// Tracks whether the menu-bar icon should show the bright J (agent
/// up) or the greyed J (agent unreachable). Mirrors the 0.2.x tray's
/// RUNNING / STOPPED states without the intermediate STARTING and
/// ERROR — Week 1's DaemonClient will refine this as needed.
enum AgentLinkState {
    case disconnected
    case connected
}
