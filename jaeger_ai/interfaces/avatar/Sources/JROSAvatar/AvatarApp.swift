// AvatarApp.swift — top-level SwiftUI scene for the JROS-Avatar
// Mac app.  Phase 1 of the 0.5.0 Swift renderer; see
// dev_docs/0.5.0_swift_renderer_plan.md for the phased plan.

import SwiftUI

@main
struct AvatarApp: App {
    @StateObject private var client = WebSocketClient()
    @StateObject private var frameStore = FrameStore()

    var body: some Scene {
        WindowGroup("JROS Avatar") {
            ContentView()
                .environmentObject(client)
                .environmentObject(frameStore)
                .frame(minWidth: 480, minHeight: 360)
        }
    }
}

/// Holds the most-recently-rendered frame for the RendererView.
/// Single-frame state (latest-wins) keeps the steady-state work
/// bounded — the AnimationNode is the source of truth for timing,
/// and SwiftUI redraws as soon as we publish a new image.
final class FrameStore: ObservableObject {
    @Published var latestImage: NSImage? = nil
    @Published var latestHeader: FrameHeader? = nil
    @Published var framesReceived: Int = 0
    @Published var bytesReceived: Int = 0
}
