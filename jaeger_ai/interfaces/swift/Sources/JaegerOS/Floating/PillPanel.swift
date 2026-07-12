//
//  PillPanel.swift
//  JaegerOS / Floating
//
//  Borderless floating panel that hosts the Claude-Code-style quick-
//  input card.  Ported in spirit from the Lilith PyQt6 ``PillWindow``
//  (FramelessWindowHint | WindowStaysOnTopHint | Tool with
//  ``WA_TranslucentBackground`` + auto-dismiss on focus loss); the
//  AppKit equivalent is an ``NSPanel`` subclass with:
//
//    • styleMask = [.nonactivatingPanel, .borderless]   ← clear
//      titlebar / no chrome / no Dock-icon thrash
//    • isFloatingPanel = true + level = .floating       ← always
//      above other windows
//    • backgroundColor = .clear + isOpaque = false      ← lets the
//      rounded SwiftUI card cast its own drop shadow over whatever
//      is below
//    • canBecomeKey = true                              ← needed so
//      the embedded NSTextField (SwiftUI TextField) gets a working
//      cursor + receives keystrokes
//
//  The panel auto-dismisses on key-resign (mirrors PyQt6's
//  ``focusOutEvent``) and on Esc (mirrors the "Not now" button).
//

import AppKit

@MainActor
final class PillPanel: NSPanel {

    /// The panel's chrome is fully off — the SwiftUI ``PillView``
    /// owns the rounded card + drop-shadow look.  ``isOpaque = false``
    /// and a clear background let the shadow render over the
    /// desktop / other windows cleanly.
    init() {
        super.init(
            contentRect: NSRect(x: 0, y: 0, width: 720, height: 160),
            styleMask: [.nonactivatingPanel, .borderless, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        isFloatingPanel = true
        level = .floating
        becomesKeyOnlyIfNeeded = false
        hidesOnDeactivate = false   // we handle dismissal ourselves
        isMovableByWindowBackground = true
        animationBehavior = .utilityWindow
        backgroundColor = .clear
        isOpaque = false
        hasShadow = false           // SwiftUI card draws its own shadow
        titleVisibility = .hidden
        titlebarAppearsTransparent = true
        collectionBehavior = [
            .canJoinAllSpaces,       // follows the operator across Spaces
            .fullScreenAuxiliary,    // visible even when another window is full-screen
            .ignoresCycle,           // not in ⌘` cycle
            .stationary,
        ]
    }

    // ``borderless`` panels normally can't become key.  We need to so
    // the SwiftUI TextField receives keystrokes.
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }

    // Esc dismisses, mirroring "Not now" in the Lilith pill.  Cmd+W
    // and Cmd+. also close — they're the conventional macOS quick-close.
    override func cancelOperation(_ sender: Any?) {
        orderOut(nil)
    }
}
