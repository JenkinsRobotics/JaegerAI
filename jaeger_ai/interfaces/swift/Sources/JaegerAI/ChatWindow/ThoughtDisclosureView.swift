//
//  ThoughtDisclosureView.swift
//  JaegerAI / ChatWindow
//
//  Claude Code style collapsible "⏱ Thought process >" disclosure row.
//  Stays permanently in the conversation transcript even after the turn finishes.
//

import SwiftUI

struct ThoughtDisclosureView: View {
    let thoughtText: String
    let isStreaming: Bool
    @State private var isExpanded: Bool = false

    var body: some View {
        if thoughtText.isEmpty && !isStreaming {
            EmptyView()
        } else {
            VStack(alignment: .leading, spacing: 6) {
                Button(action: { withAnimation(.easeInOut(duration: 0.2)) { isExpanded.toggle() } }) {
                    HStack(spacing: 6) {
                        Image(systemName: "clock")
                            .font(.system(size: 11))
                            .foregroundColor(Term.inkDim)
                        Text("Thought process")
                            .font(.system(size: 12, weight: .medium, design: .monospaced))
                            .foregroundColor(Term.inkDim)
                        Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                            .font(.system(size: 10, weight: .bold))
                            .foregroundColor(Term.inkDim.opacity(0.8))
                        if isStreaming {
                            ThinkingDots()
                                .scaleEffect(0.8)
                        }
                        Spacer()
                    }
                    .padding(.vertical, 4)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)

                if isExpanded {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(thoughtText.isEmpty ? "Thinking…" : thoughtText)
                            .font(.system(size: 12, design: .monospaced))
                            .foregroundColor(Term.ink.opacity(0.85))
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(10)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(
                                RoundedRectangle(cornerRadius: 6)
                                    .fill(Term.panel.opacity(0.8))
                            )
                            .overlay(
                                RoundedRectangle(cornerRadius: 6)
                                    .strokeBorder(Term.rule.opacity(0.6), lineWidth: 1)
                            )
                    }
                    .transition(.opacity.combined(with: .move(edge: .top)))
                }
            }
            .padding(.leading, 6)
        }
    }
}
