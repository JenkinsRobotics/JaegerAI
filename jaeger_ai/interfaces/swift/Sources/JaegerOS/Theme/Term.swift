//
//  Term.swift
//  JaegerOS / Theme
//
//  The Rich terminal TUI's palette, ported 1:1 so every windowed surface
//  reads as "the same app in a clean window."  Accent is the TUI's
//  ``theme._ACCENT_HEX`` (#3aa0ff); the canvas is a near-black terminal
//  ground rather than the system window colour.  Shared by the chat
//  window, the avatar surfaces, and any future dark-canvas view — one
//  palette, no per-file copies.
//

import SwiftUI

enum Term {
    static let accent  = Color(red: 0.227, green: 0.627, blue: 1.000) // #3aa0ff
    static let canvas  = Color(red: 0.043, green: 0.055, blue: 0.078) // #0B0E14
    static let panel   = Color(red: 0.075, green: 0.090, blue: 0.122) // #131720
    static let ink     = Color(red: 0.866, green: 0.886, blue: 0.918) // #DDE2EA
    static let inkDim  = Color(red: 0.533, green: 0.560, blue: 0.612) // #888F9C
    static let rule    = Color(red: 0.227, green: 0.627, blue: 1.000).opacity(0.25)
    static let mono    = Font.system(size: 13, design: .monospaced)
}
