//
//  InteractivePromptView.swift
//  JaegerAI / ChatWindow
//
//  Renders interactive clickable choice chips (A / B / C) when the
//  agent asks collaboration or confirmation questions in the feed.
//

import SwiftUI

struct InteractivePromptView: View {
    let question: String
    let options: [String]
    let onSelect: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: "questionmark.circle.fill")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Term.accent)
                Text(question.isEmpty ? "Decision Required" : question)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Term.ink)
            }
            .padding(.bottom, 2)

            ForEach(options, id: \.self) { opt in
                Button(action: { onSelect(opt) }) {
                    optionRow(opt)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: 6)
                .fill(Term.panel)
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(Term.rule, lineWidth: 1)
                )
        )
    }

    private func optionRow(_ opt: String) -> some View {
        HStack(spacing: 8) {
            Circle()
                .fill(Term.accent)
                .frame(width: 5, height: 5)
            Text(opt)
                .font(.system(size: 12))
                .foregroundStyle(Term.ink)
            Spacer()
            Image(systemName: "chevron.right")
                .font(.system(size: 9))
                .foregroundStyle(Term.inkDim)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 4)
                .fill(Term.canvas)
        )
    }
}
