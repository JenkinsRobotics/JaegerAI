// ContentView.swift — primary window content for JROS-Avatar.
// Phase 1: connection field + status indicator + renderer canvas.

import SwiftUI

struct ContentView: View {
    @EnvironmentObject var client: WebSocketClient
    @EnvironmentObject var frameStore: FrameStore
    @State private var urlText: String = "ws://127.0.0.1:8765/frames"

    var body: some View {
        VStack(spacing: 8) {
            HStack {
                TextField("WebSocket URL", text: $urlText)
                    .textFieldStyle(.roundedBorder)
                Button(client.isConnected ? "Disconnect" : "Connect") {
                    if client.isConnected {
                        client.disconnect()
                    } else {
                        if let url = URL(string: urlText) {
                            client.connect(to: url, store: frameStore)
                        }
                    }
                }
            }
            .padding(.horizontal)
            .padding(.top, 8)

            statusBar

            Divider()

            RendererView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private var statusBar: some View {
        HStack(spacing: 16) {
            Circle()
                .fill(client.isConnected ? .green : .gray)
                .frame(width: 8, height: 8)
            Text(client.isConnected ? "Connected" : "Disconnected")
                .font(.caption)
                .foregroundColor(.secondary)
            Spacer()
            Text("\(frameStore.framesReceived) frames")
                .font(.caption.monospaced())
                .foregroundColor(.secondary)
            Text("\(formatBytes(frameStore.bytesReceived))")
                .font(.caption.monospaced())
                .foregroundColor(.secondary)
        }
        .padding(.horizontal)
    }

    private func formatBytes(_ n: Int) -> String {
        let kb = Double(n) / 1024
        if kb < 1024 { return String(format: "%.1f KB", kb) }
        let mb = kb / 1024
        return String(format: "%.1f MB", mb)
    }
}
