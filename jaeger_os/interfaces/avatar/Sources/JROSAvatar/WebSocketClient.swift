// WebSocketClient.swift — minimal URLSessionWebSocketTask wrapper.
// Receives binary frames from JROS, hands them to FrameDecoder, and
// updates the shared FrameStore that RendererView observes.

import Combine
import Foundation
import AppKit

@MainActor
final class WebSocketClient: ObservableObject {
    @Published private(set) var isConnected: Bool = false
    @Published private(set) var lastError: String? = nil

    private var task: URLSessionWebSocketTask? = nil
    private var session: URLSession? = nil
    private weak var store: FrameStore? = nil

    func connect(to url: URL, store: FrameStore) {
        disconnect()
        let session = URLSession(configuration: .default)
        let task = session.webSocketTask(with: url)
        self.session = session
        self.task = task
        self.store = store
        task.resume()
        isConnected = true
        lastError = nil
        receive()
    }

    func disconnect() {
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        session?.invalidateAndCancel()
        session = nil
        isConnected = false
    }

    private func receive() {
        task?.receive { [weak self] result in
            guard let self else { return }
            Task { @MainActor in
                switch result {
                case .failure(let err):
                    self.isConnected = false
                    self.lastError = "\(err.localizedDescription)"
                case .success(let msg):
                    self.handle(msg)
                    self.receive()
                }
            }
        }
    }

    private func handle(_ msg: URLSessionWebSocketTask.Message) {
        guard let store = store else { return }
        switch msg {
        case .data(let data):
            do {
                let frame = try FrameDecoder.decode(data)
                store.latestImage = frame.image
                store.latestHeader = frame.header
                store.framesReceived += 1
                store.bytesReceived += data.count
            } catch {
                lastError = "decode: \(error)"
            }
        case .string(let s):
            // Phase 1: text channel carries state events (later).
            // For now, just log the first 80 chars.
            lastError = String(s.prefix(80))
        @unknown default:
            break
        }
    }
}
