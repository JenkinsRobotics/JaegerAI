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
        VStack(alignment: .leading, spacing: 8) {
            // First 3 items or all if expanded
            let visibleItems = isExpanded ? items : Array(items.prefix(3))
            ForEach(visibleItems) { item in
                HStack(alignment: .top, spacing: 8) {
                    Text(cleanToolName(item.name))
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        .foregroundColor(item.ok ? Term.ink : Color.red)
                    if !item.detail.isEmpty {
                        Text(item.detail)
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundColor(Term.inkDim)
                            .lineLimit(isExpanded ? 3 : 1)
                    }
                    Spacer()
                    if item.isStreaming {
                        ProgressView().controlSize(.mini)
                    } else if item.elapsed_s > 0.05 {
                        Text(String(format: "%.1fs", item.elapsed_s))
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundColor(Term.inkDim.opacity(0.8))
                    }
                }
            }

            if items.count > 3 || !items.isEmpty {
                Button(action: { withAnimation(.easeInOut(duration: 0.2)) { isExpanded.toggle() } }) {
                    HStack(spacing: 4) {
                        Text(isExpanded ? "Show less" : "Show more")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundColor(Term.inkDim)
                        Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundColor(Term.inkDim)
                    }
                    .padding(.top, 2)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color(red: 0.05, green: 0.06, blue: 0.08))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .strokeBorder(Color.white.opacity(0.08), lineWidth: 1)
        )
        .padding(.vertical, 4)
    }
}
