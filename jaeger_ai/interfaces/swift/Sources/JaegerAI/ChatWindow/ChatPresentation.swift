import Foundation
import SwiftUI

/// Presentation rules only. Gateway/bridge remain the owners of execution.
enum ChatPresentation {
    static let contentWidth: CGFloat = 900
    static let canvas = Color(white: 0.095)
    static let composer = Color(white: 0.16)

    static func modelLabel(_ model: String?) -> String {
        let name = (model ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return name.isEmpty ? "Choose model" : name
    }

    static func canSubmit(text: String, attachmentCount: Int, connected: Bool,
                          transcribing: Bool, switchingSession: Bool,
                          dispatcherBusy: Bool) -> Bool {
        connected && !transcribing && !switchingSession && !dispatcherBusy
            && (!text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || attachmentCount > 0)
    }

    static func toolName(_ raw: String) -> String {
        // MCP names include transport/server prefixes; retain the actual tool name.
        let name = raw.hasPrefix("mcp__") ? (raw.components(separatedBy: "__").last ?? raw) : raw
        return name.replacingOccurrences(of: "_", with: " ")
    }

    static func activityTitle(items: [ToolCallItem], running: Bool) -> String {
        guard let first = items.first else { return running ? "Working" : "Activity" }
        if items.count == 1 {
            return "\(running ? "Using" : "Used") \(toolName(first.name))"
        }
        return "\(running ? "Using" : "Used") \(items.count) tools"
    }
}

struct ChatRunStatusView: View {
    let startedAt: Date
    let onStop: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            ProgressView().controlSize(.small)
            Text("Working")
            Text(startedAt, style: .timer).monospacedDigit()
            Spacer()
            Button("Stop", systemImage: "stop.fill", action: onStop)
                .buttonStyle(.plain)
                .accessibilityLabel("Stop current task")
        }
        .font(.system(size: 12))
        .foregroundStyle(Term.inkDim)
        .padding(.vertical, 10)
        .frame(maxWidth: ChatPresentation.contentWidth)
        .padding(.horizontal, 24)
        .frame(maxWidth: .infinity)
    }
}
