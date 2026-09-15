//
//  ToolCommandGroupView.swift
//  JaegerAI / ChatWindow
//
//  Collapsible "Ran N commands" tool section. One section per uninterrupted
//  run of tool calls (``TranscriptFeed`` splits them whenever the agent
//  thinks or answers in between), so a section is always a contiguous piece
//  of the turn rather than every tool the turn ever ran.
//
//  Stays in the transcript permanently once the turn finishes.
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

    /// Set only once the operator clicks. Until then the section follows the
    /// run: open while the tools are executing so the work is visible, shut
    /// when they settle so a finished turn reads as its answer rather than
    /// its mechanics. A deliberate choice outranks that for the rest of the
    /// session — collapsing a section the operator just opened (or reopening
    /// one they shut) to follow a late ``tool.result`` would fight them.
    @State private var expandedOverride: Bool?

    private var isExpanded: Bool { expandedOverride ?? isStreaming }

    /// Failures stay findable while collapsed — the one thing worth
    /// surfacing from a section the operator can't see into.
    private var failureCount: Int { items.filter { !$0.ok && !$0.isStreaming }.count }

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
            header
            if isExpanded {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(items) { item in
                        row(item)
                    }
                }
                .transition(.opacity.combined(with: .move(edge: .top)))
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

    private var header: some View {
        Button(action: {
            withAnimation(.easeInOut(duration: 0.2)) { expandedOverride = !isExpanded }
        }) {
            HStack(spacing: 6) {
                Image(systemName: "terminal")
                    .font(.system(size: 11))
                    .foregroundColor(Term.inkDim)
                Text(summaryTitle)
                    .font(.system(size: 12, weight: .medium, design: .monospaced))
                    .foregroundColor(Term.inkDim)
                    .lineLimit(1)
                Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundColor(Term.inkDim.opacity(0.8))
                if isStreaming {
                    ProgressView().controlSize(.mini)
                } else if !isExpanded && failureCount > 0 {
                    Text("\(failureCount) failed")
                        .font(.system(size: 10, weight: .semibold, design: .monospaced))
                        .foregroundColor(.red)
                }
                Spacer(minLength: 0)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(summaryTitle)
        .accessibilityHint(isExpanded ? "Collapse tool details" : "Expand tool details")
    }

    private func row(_ item: ToolCallItem) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(cleanToolName(item.name))
                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                .foregroundColor(item.ok ? Term.ink : Color.red)
            if !item.detail.isEmpty {
                Text(item.detail)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(Term.inkDim)
                    .lineLimit(3)
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
}
