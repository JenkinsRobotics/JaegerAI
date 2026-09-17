import AppKit
import SwiftUI

struct ServerStatus: Decodable, Identifiable {
    let id: String
    let name: String
    let ready: Bool
    let configured: Bool
    let state: String
}

struct ServerReply: Decodable {
    let ok: Bool
    let error: String?
    let services: [ServerStatus]
}

private enum ServerControlError: LocalizedError {
    case noResponse(String)
    case invalidResponse(String)

    var errorDescription: String? {
        switch self {
        case .noResponse(let detail):
            return "Server controls did not respond. \(detail)"
        case .invalidResponse(let detail):
            return "Server controls returned invalid data. \(detail)"
        }
    }
}

@MainActor
final class ServerControls: ObservableObject {
    @Published var services: [ServerStatus] = []
    @Published var busy = false
    @Published var error: String?
    private var refreshing = false

    private func request(_ arguments: [String]) async throws -> ServerReply {
        try await Task.detached {
            let process = Process()
            let outputPipe = Pipe()
            let errorPipe = Pipe()
            process.executableURL = URL(fileURLWithPath: BridgeProcess.jaegerPath())
            process.arguments = ["webui", "servers"] + arguments
            process.standardOutput = outputPipe
            process.standardError = errorPipe
            try process.run()
            let watchdog = Task {
                try? await Task.sleep(for: .seconds(180))
                if !Task.isCancelled && process.isRunning { process.terminate() }
            }
            defer { watchdog.cancel() }
            let data = outputPipe.fileHandleForReading.readDataToEndOfFile()
            let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            let stderr = String(data: errorData, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            guard !data.isEmpty else {
                let detail = stderr.isEmpty
                    ? "Command exited with status \(process.terminationStatus)."
                    : stderr
                throw ServerControlError.noResponse(detail)
            }
            do {
                return try JSONDecoder().decode(ServerReply.self, from: data)
            } catch {
                let detail = stderr.isEmpty ? error.localizedDescription : stderr
                throw ServerControlError.invalidResponse(detail)
            }
        }.value
    }

    func refresh() async {
        guard !busy && !refreshing else { return }
        refreshing = true
        defer { refreshing = false }
        do {
            let reply = try await request(["status"])
            services = reply.services
            error = reply.ok ? nil : reply.error
        } catch { self.error = error.localizedDescription }
    }

    func change(_ action: String, service: String) async {
        guard !busy else { return }
        busy = true
        error = nil
        do {
            let reply = try await request([action, service])
            services = reply.services
            error = reply.ok ? nil : reply.error
        } catch { self.error = error.localizedDescription }
        busy = false
    }

    func openWebUI() async {
        do { NSWorkspace.shared.open(try await WebUIEndpoint.resolve()) }
        catch { self.error = error.localizedDescription }
    }
}

struct ServerControlsView: View {
    @StateObject private var controls = ServerControls()

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("Servers", systemImage: "server.rack").font(.system(size: 12, weight: .semibold))
                Spacer()
                if controls.busy { ProgressView().controlSize(.mini) }
                Button { Task { await controls.refresh() } } label: {
                    Image(systemName: "arrow.clockwise")
                }.buttonStyle(.plain).help("Refresh server status").disabled(controls.busy)
            }
            if controls.services.isEmpty {
                Text("Checking servers…").font(.caption).foregroundStyle(.secondary)
            }
            ForEach(controls.services) { service in
                HStack(spacing: 6) {
                    Circle().fill(service.ready ? Color.green : Color.orange).frame(width: 7, height: 7)
                    Text(service.name).font(.system(size: 12))
                    Spacer()
                    Text(service.state).font(.system(size: 10)).foregroundStyle(.secondary)
                    Menu {
                        Button("Start") { change("start", service.id) }
                            .disabled(!service.configured)
                        Button("Restart") { change("restart", service.id) }
                            .disabled(!service.configured)
                        Button("Stop") { change("stop", service.id) }
                    } label: { Image(systemName: "ellipsis.circle") }
                    .menuStyle(.borderlessButton).fixedSize().disabled(controls.busy)
                    .help("Manage \(service.name)")
                }
            }
            HStack {
                Button("Start All") { change("start", "all") }
                Button("Stop All") { change("stop", "all") }
                Spacer()
                Button { Task { await controls.openWebUI() } } label: {
                    Image(systemName: "globe")
                }.help("Open Web UI")
            }.controlSize(.small).disabled(controls.busy)
            Text("Stop or restart interrupts active chats.")
                .font(.system(size: 10)).foregroundStyle(.secondary)
            if let error = controls.error {
                Text(error).font(.caption).foregroundStyle(.red).textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
        .task {
            while !Task.isCancelled {
                await controls.refresh()
                try? await Task.sleep(for: .seconds(5))
            }
        }
    }

    private func change(_ action: String, _ service: String) {
        Task { await controls.change(action, service: service) }
    }
}
