//
//  ToolCommandGroupView.swift
//  JaegerAI / ChatWindow
//
//  Claude Code style "Ran N commands >" collapsible tool group disclosure.
//  Stays permanently in the conversation transcript.
//

import SwiftUI

public struct ToolCallItem: Identifiable, Equatable {
    public let id = UUID()
    public var name: String
    public var detail: String
    public var elapsed_s: Double
    public var ok: Bool
    public var isStreaming: Bool

    public init(name: String, detail: String = "", elapsed_s: Double = 0, ok: Bool = true, isStreaming: Bool = false) {
        self.name = name
        self.detail = detail
        self.elapsed_s = elapsed_s
        self.ok = ok
        self.isStreaming = isStreaming
    }
}

struct ToolCommandGroupView: View {
    let items: [ToolCallItem]
    let isStreaming: Bool
    @State private var isExpanded: Bool = false

    private var summaryTitle: String {
        if items.count <= 1, let single = items.first {
            let base = "Ran \(cleanToolName(single.name))"
            if !single.detail.isEmpty {
                return "\(base) · \(single.detail)"
            }
            return base
        }
        return "Ran \(items.count) command\(items.count == 1 ? "" : "s")"
    }

    private func cleanToolName(_ raw: String) -> String {
        return raw.replacingOccurrences(of: "mcp__ares-native__", with: "")
                  .replacingOccurrences(of: "mcp__", with: "")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Button(action: { withAnimation(.easeInOut(duration: 0.2)) { isExpanded.toggle() } }) {
                HStack(spacing: 6) {
                    Text(summaryTitle)
                        .font(.system(size: 12, weight: .medium, design: .monospaced))
                        .foregroundColor(Term.inkDim)
                    Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundColor(Term.inkDim.opacity(0.8))
                    if isStreaming {
                        ProgressView().controlSize(.mini)
                    }
                    Spacer()
                }
                .padding(.vertical, 4)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if isExpanded {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(items) { item in
                        HStack(alignment: .top, spacing: 8) {
                            Text("⏵")
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundColor(item.ok ? Term.accent : Color.red)
                            Text(cleanToolName(item.name))
                                .font(.system(size: 12, weight: .semibold, design: .monospaced))
                                .foregroundColor(Term.ink)
                            if !item.detail.isEmpty {
                                Text(item.detail)
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundColor(Term.inkDim)
                                    .lineLimit(1)
                            }
                            Spacer()
                            if item.isStreaming {
                                ProgressView().controlSize(.mini)
                            } else {
                                Text(item.ok ? "✓" : "✗")
                                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                                    .foregroundColor(item.ok ? Term.accent : Color.red)
                                if item.elapsed_s > 0.05 {
                                    Text(String(format: "%.1fs", item.elapsed_s))
                                        .font(.system(size: 10, design: .monospaced))
                                        .foregroundColor(Term.inkDim.opacity(0.8))
                                }
                            }
                        }
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                        .background(
                            RoundedRectangle(cornerRadius: 4)
                                .fill(Term.panel.opacity(0.6))
                        )
                    }
                }
                .padding(.leading, 12)
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .padding(.leading, 6)
    }
}
