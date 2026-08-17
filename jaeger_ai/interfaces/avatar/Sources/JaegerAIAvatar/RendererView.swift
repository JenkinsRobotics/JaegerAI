// RendererView.swift — displays the latest decoded frame.  Phase 1
// shows a placeholder when no frames have arrived; phase 2+ moves
// to a Metal-backed view for performance once frame rates demand it.

import SwiftUI

struct RendererView: View {
    @EnvironmentObject var frameStore: FrameStore

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if let image = frameStore.latestImage {
                Image(nsImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .padding()
            } else {
                VStack(spacing: 12) {
                    Image(systemName: "face.smiling.inverse")
                        .font(.system(size: 96))
                        .foregroundColor(.white.opacity(0.3))
                    Text("Waiting for frames…")
                        .foregroundColor(.white.opacity(0.4))
                        .font(.callout)
                    if let h = frameStore.latestHeader {
                        Text("last: \(h.asset)")
                            .font(.caption.monospaced())
                            .foregroundColor(.white.opacity(0.2))
                    }
                }
            }
        }
    }
}
