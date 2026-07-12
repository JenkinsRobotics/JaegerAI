//
//  PillView.swift
//  JaegerOS / Floating
//
//  SwiftUI card that fills the ``PillPanel``.  Two-row layout from the
//  Lilith PyQt6 ``PillWindow``:
//
//    ┌─────────────────────────────────────────────────────────────┐
//    │  🎇  [ What can I help you with today?         ] New Chat ▾  ↑ │
//    │  ───────────────────────────────────────────────────────────  │
//    │  Quickly share content with Jaeger      Turn on …    Not now │
//    │  Needs additional permission                                  │
//    └─────────────────────────────────────────────────────────────┘
//
//  Palette is 1:1 with the Lilith original — a forced-light Claude-style
//  card (``#F7F7F8`` surface, ``#007AFF`` send) regardless of the macOS
//  appearance, so the launcher reads identically to the archive.  Send
//  routes via ``PillActions.submit`` (the controller wires it to the
//  chat window) instead of a direct Qt-signal connection, and the
//  "New Chat ▾" dropdown is a SwiftUI ``Menu`` (native NSMenu).
//

import SwiftUI

/// Exact hex values from the Lilith ``PillWindow`` stylesheet so the
/// Swift launcher is 1:1 with the archive.  Forced-light (not
/// system-adaptive) — the Claude quick-input look is a light card.
private enum Pill {
    static let card      = Color(red: 0.969, green: 0.969, blue: 0.973) // #F7F7F8
    static let border    = Color(red: 0.898, green: 0.906, blue: 0.922) // #E5E7EB
    static let ink       = Color(red: 0.133, green: 0.133, blue: 0.133) // #222222
    static let inkMuted  = Color(red: 0.400, green: 0.400, blue: 0.400) // #666666
    static let inkFaint  = Color(red: 0.533, green: 0.533, blue: 0.533) // #888888
    static let accent    = Color(red: 0.000, green: 0.478, blue: 1.000) // #007AFF
    static let accentOff = Color(red: 0.698, green: 0.851, blue: 1.000) // #B2D9FF
    static let chipFill  = Color(red: 0.922, green: 0.922, blue: 0.922) // #EBEBEB
    static let chipEdge  = Color(red: 0.875, green: 0.875, blue: 0.875) // #DFDFDF
}

struct PillView: View {

    /// Auto-focused on appearance so ``⌥Space`` → type instantly works.
    @FocusState private var inputFocused: Bool

    @State private var draft: String = ""

    /// Shared mutable state with the controller + chat window —
    /// ``revealToken`` triggers refocus on each show (the panel is
    /// reused, so ``.onAppear`` only fires the first time);
    /// ``isAgentBusy`` mirrors ``ChatViewModel.isSending`` so the
    /// send button can disable instead of silently dropping into
    /// the chat model's own busy-guard.
    @EnvironmentObject private var bridge: PillBridge

    /// Callback the controller installs so it can drive lifecycle
    /// (dismiss / open chat window / etc.) without the view having
    /// to know about NSWindow.
    let actions: PillActions

    /// Trimmed once per body eval so the background fill, disabled
    /// state, and send guard all read from the same source.
    private var trimmedDraft: String {
        draft.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Send is enabled when there's text AND the agent isn't already
    /// chewing on a previous turn.  Disabling on busy is the visible
    /// signal that earlier review-pass review flagged (silently
    /// dropped pill submissions while ``ChatViewModel`` was sending).
    private var canSend: Bool {
        !trimmedDraft.isEmpty && !bridge.isAgentBusy
    }

    var body: some View {
        // Outer padding gives the drop shadow room to render without
        // being clipped by the panel's content rect.
        VStack(spacing: 0) {
            cardBody
        }
        .padding(20)
        .background(.clear)
        .onAppear { inputFocused = true }
        // Panel reuse: ``revealToken`` changes on every
        // ``PillPanelController.toggle`` show path, restoring
        // focus even though ``.onAppear`` doesn't fire again.
        .onChange(of: bridge.revealToken) { _, _ in
            inputFocused = true
        }
    }

    private var cardBody: some View {
        VStack(spacing: 10) {
            // ── Top row: icon + input + dropdown + send ─────────────
            HStack(spacing: 12) {
                PillGlyph()

                TextField("What can I help you with today?", text: $draft)
                    .textFieldStyle(.plain)
                    .font(.system(size: 16))
                    .foregroundColor(Pill.ink)
                    .focused($inputFocused)
                    .submitLabel(.send)
                    .onSubmit(send)
                    .frame(maxWidth: .infinity)   // fill the card, don't collapse

                Menu("New Chat ▾") {
                    Button("Open Chat Window") { actions.openChatWindow() }
                    Divider()
                    Button("Dismiss Pill") { actions.dismiss() }
                }
                .menuStyle(.borderlessButton)
                .fixedSize()
                .font(.system(size: 14))
                .foregroundColor(Pill.inkMuted)

                // 32×32 #007AFF send — disabled fades to #B2D9FF, matching
                // the Lilith ``QPushButton:disabled`` style exactly.
                Button(action: send) {
                    Image(systemName: "arrow.up")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundColor(.white)
                        .frame(width: 32, height: 32)
                        .background(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(canSend ? Pill.accent : Pill.accentOff)
                        )
                }
                .buttonStyle(.plain)
                .disabled(!canSend)
                .help(bridge.isAgentBusy
                      ? "Agent is processing the previous turn…"
                      : "Send")
                .keyboardShortcut(.return, modifiers: [])
            }

            Rectangle()
                .fill(Pill.border)
                .frame(height: 1)

            // ── Bottom row: callouts + pill buttons ────────────────
            HStack(alignment: .center, spacing: 10) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Quickly share content with Jaeger")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundColor(Pill.ink)
                    Text("Needs additional permission")
                        .font(.system(size: 11))
                        .foregroundColor(Pill.inkFaint)
                }

                Spacer()

                // Placeholder pill buttons — Lilith PyQt6 had identical
                // affordances (Turn on screenshots / Not now).  Wired
                // to the same dismiss path so the operator's muscle
                // memory transfers.
                pillButton("Turn on screenshots") { actions.notImplemented("Screenshots") }
                pillButton("Not now") { actions.dismiss() }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Pill.card)
                .shadow(color: .black.opacity(0.12), radius: 12, x: 0, y: 8)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(Pill.border, lineWidth: 1)
        )
        .frame(width: 680)   // the panel is 720; fill it (was collapsing to text width)
    }

    @ViewBuilder
    private func pillButton(_ label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(label)
                .font(.system(size: 12))
                .foregroundColor(Pill.ink)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .fill(Pill.chipFill)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .stroke(Pill.chipEdge, lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
    }

    private func send() {
        guard canSend else { return }
        actions.submit(trimmedDraft)
        draft = ""
    }
}

/// The J brand mark (jaeger_icon_22.png), matching the PySide6 pill.
/// Falls back to the sparkler glyph if the asset isn't bundled.
private struct PillGlyph: View {
    var body: some View {
        if let url = Bundle.module.url(forResource: "jaeger_icon_22",
                                       withExtension: "png"),
           let img = NSImage(contentsOf: url) {
            Image(nsImage: img)
                .resizable()
                .interpolation(.high)
                .frame(width: 22, height: 22)
        } else {
            Text("🎇").font(.system(size: 22))
        }
    }
}

// MARK: - Plumbing types

/// Callbacks the panel controller hands the view so the view stays
/// ignorant of NSWindow / NotificationCenter / agent details.
struct PillActions {
    let submit: (_ text: String) -> Void
    let dismiss: () -> Void
    let openChatWindow: () -> Void
    let notImplemented: (_ what: String) -> Void
}
