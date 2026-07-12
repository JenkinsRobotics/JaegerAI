//
//  PillBridge.swift
//  JaegerOS / Floating
//
//  Shared mutable state between the floating pill and the chat
//  window.  Replaces the first iteration's ``NotificationCenter``
//  hop, which had three known weaknesses:
//
//    1. First-launch race — ``handleSubmit`` raised the chat window
//       (creating its view tree) and then immediately posted the
//       notification, but SwiftUI's ``.onReceive`` subscription is
//       installed during the view tree's first layout pass.  On a
//       cold launch the post fired BEFORE the subscription existed
//       and the prompt was silently dropped.
//    2. Focus reset — the pill's ``@FocusState`` was tied to
//       ``.onAppear``, but the panel is reused across ⌥Space toggles,
//       so the TextField didn't refocus on subsequent shows.
//    3. Send-while-busy — concurrent submissions hit
//       ``ChatViewModel.send``'s ``isSending`` guard and were
//       silently dropped; the pill's UI had no way to know.
//
//  ``PillBridge`` is a ``@MainActor`` singleton ``ObservableObject``
//  that solves all three at once:
//
//    * ``pendingPrompt: String?`` — controller writes; ChatView
//      observes via ``.onChange`` AND drains in ``.onAppear`` so
//      "view just mounted" and "view already mounted" both work.
//    * ``revealToken: UUID`` — controller mints a fresh UUID on
//      each show; the pill view watches ``.onChange`` to flip
//      ``inputFocused = true`` even when the panel is being reused.
//    * ``isAgentBusy: Bool`` — ChatView mirrors ``chat.isSending``
//      here; the pill's send button respects it so the operator
//      never submits into a black hole.
//

import Combine
import Foundation

@MainActor
final class PillBridge: ObservableObject {

    /// Process-wide singleton.  Mirrors ``AgentBridge.shared`` /
    /// ``ChatWindowController.shared`` so the floating surface
    /// stays consistent with the rest of the app's accessor
    /// conventions.
    static let shared = PillBridge()

    /// Prompt the floating pill captured but hasn't yet been
    /// consumed by the chat view.  ChatView drains this into
    /// ``chat.send`` and writes ``nil`` back.  Optional so a fresh
    /// chat window without a pending prompt doesn't fire a phantom
    /// submission on first appearance.
    @Published var pendingPrompt: String?

    /// Bumped to a fresh UUID every time the pill panel is shown.
    /// PillView observes ``.onChange(of:)`` so the TextField focus
    /// is restored on every reveal, including when the panel is
    /// being reused (``.onAppear`` doesn't fire then).
    @Published var revealToken: UUID = UUID()

    /// Mirror of ``ChatViewModel.isSending``.  Written by ChatView
    /// via ``.onChange``; read by PillView so the send button can
    /// disable itself while a turn is in flight (the chat model's
    /// own ``isSending`` guard would otherwise silently drop a
    /// pill submission).
    @Published var isAgentBusy: Bool = false

    private init() {}
}
