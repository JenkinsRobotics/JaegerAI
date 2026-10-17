import AppKit
import SwiftUI

public struct WorkspaceView: View {
    @State private var snapshot: WorkspaceSnapshot?
    @State private var error: String?
    @State private var isLoading = false

    public init() {}

    public var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .center) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Repository")
                        .font(.title2.weight(.semibold))
                    Text(snapshot?.repoRoot.path ?? repoRoot.path)
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .textSelection(.enabled)
                }
                Spacer()
                Button { refresh() } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.bordered)
                .help("Refresh repository status")
                Button("Show in Finder") {
                    NSWorkspace.shared.activateFileViewerSelecting([snapshot?.repoRoot ?? repoRoot])
                }
                .buttonStyle(.bordered)
            }
            .padding(20)

            if let snapshot {
                HStack(spacing: 8) {
                    Image(systemName: "arrow.triangle.branch")
                    Text(snapshot.branch).font(.system(.body, design: .monospaced))
                    Spacer()
                    Text(snapshot.changes.isEmpty ? "Clean" : "\(snapshot.changes.count) changes")
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 12)
                Divider()
                if snapshot.changes.isEmpty {
                    ContentUnavailableView("Working tree is clean", systemImage: "checkmark.circle")
                } else {
                    List(snapshot.changes) { change in
                        HStack(spacing: 12) {
                            Text(change.badge)
                                .font(.system(.caption, design: .monospaced).weight(.bold))
                                .foregroundStyle(statusColor(change.badge))
                                .frame(width: 18)
                            Text(change.path)
                                .font(.system(.callout, design: .monospaced))
                                .lineLimit(1)
                                .truncationMode(.middle)
                            Spacer()
                        }
                        .padding(.vertical, 2)
                    }
                    .listStyle(.inset)
                }
            } else if isLoading {
                ProgressView("Reading repository…").frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let error {
                ContentUnavailableView(error, systemImage: "exclamationmark.triangle")
            }
        }
        .task { if snapshot == nil { refresh() } }
        .frame(minWidth: 520, minHeight: 360)
    }

    private var repoRoot: URL {
        let environment = ProcessInfo.processInfo.environment
        if let path = environment["JAEGER_REPO"], !path.isEmpty {
            return URL(fileURLWithPath: path).standardizedFileURL
        }
        var location = Bundle.main.bundleURL.standardizedFileURL
        for _ in 0..<10 {
            if FileManager.default.isExecutableFile(atPath: location.appendingPathComponent("jaeger").path),
               FileManager.default.fileExists(atPath: location.appendingPathComponent("pyproject.toml").path) {
                return location
            }
            let parent = location.deletingLastPathComponent()
            if parent == location { break }
            location = parent
        }
        let fallback = URL(fileURLWithPath: NSHomeDirectory())
            .appendingPathComponent("GitHub/JaegerAI", isDirectory: true)
        return fallback
    }

    private func refresh() {
        guard !isLoading else { return }
        isLoading = true
        error = nil
        let root = repoRoot
        Task.detached {
            let result = Result { try WorkspaceSnapshot.load(repoRoot: root) }
            await MainActor.run {
                switch result {
                case .success(let value): snapshot = value
                case .failure(let failure): error = failure.localizedDescription
                }
                isLoading = false
            }
        }
    }

    private func statusColor(_ status: String) -> Color {
        switch status {
        case "?", "A": .green
        case "D": .red
        default: .orange
        }
    }
}
