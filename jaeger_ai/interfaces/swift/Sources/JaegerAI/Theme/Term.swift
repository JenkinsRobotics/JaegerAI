//
//  Term.swift
//  JaegerAI / Theme
//
//  The Rich terminal TUI's palette, ported 1:1 so every windowed surface
//  reads as "the same app in a clean window."  Accent is the TUI's
//  ``theme._ACCENT_HEX`` (#3aa0ff); the canvas is a near-black terminal
//  ground rather than the system window colour.  Shared by the chat
//  window, the avatar surfaces, and any future dark-canvas view — one
//  palette, no per-file copies.
//

import SwiftUI

// Term bridges directly to AetherTheme so that native macOS windowed surfaces,
// chat windows, avatar views, and HUD cards read as one visual family with
// Aether Studio while preserving Jaeger's native identity.
enum Term {
    static let accent   = AetherTheme.accent
    static let canvas   = AetherTheme.bgApp
    static let panel    = AetherTheme.bgShell
    static let ink      = AetherTheme.text
    static let inkDim   = AetherTheme.textDim
    static let rule     = AetherTheme.border
    static let selected = AetherTheme.bgSelected
    static let mono     = Font.system(size: 13, design: .monospaced)
    static let uiBody   = AetherTheme.fontBody

    // Geometry tokens
    static let radiusControl = AetherTheme.radiusControl
    static let radiusButton  = AetherTheme.radiusButton
    static let radiusField   = AetherTheme.radiusField
    static let radiusRow     = AetherTheme.radiusRow
}

