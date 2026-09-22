//
//  MarkdownMathFormatter.swift
//  JaegerAI / Features / Math
//
//  LaTeX and Markdown Math parsing utilities ported from Hermex architecture.
//

import Foundation
import SwiftUI

public enum MathBlockType: Equatable, Sendable {
    case inline(String)
    case block(String)
    case text(String)
}

public struct MarkdownMathFormatter {
    private static let blockMathPattern = try? NSRegularExpression(pattern: #"\$\$(.*?)\$\$"#, options: [.dotMatchesLineSeparators])
    private static let inlineMathPattern = try? NSRegularExpression(pattern: #"\$([^$\n]+?)\$"#, options: [])

    public static func segment(_ input: String) -> [MathBlockType] {
        guard !input.isEmpty else { return [] }
        var segments: [MathBlockType] = []

        // Split by block math first ($$ ... $$)
        let parts = input.components(separatedBy: "$$")
        if parts.count == 1 {
            // No block math, check inline
            return segmentInline(input)
        }

        for (index, part) in parts.enumerated() {
            if index % 2 == 1 {
                // Inside $$
                let trimmed = part.trimmingCharacters(in: .whitespacesAndNewlines)
                if !trimmed.isEmpty {
                    segments.append(.block(trimmed))
                }
            } else {
                // Outside $$
                segments.append(contentsOf: segmentInline(part))
            }
        }
        return segments
    }

    private static func segmentInline(_ input: String) -> [MathBlockType] {
        guard !input.isEmpty else { return [] }
        var result: [MathBlockType] = []
        let components = input.components(separatedBy: "$")

        if components.count == 1 {
            return [.text(input)]
        }

        for (index, comp) in components.enumerated() {
            if index % 2 == 1 {
                let trimmed = comp.trimmingCharacters(in: .whitespacesAndNewlines)
                if !trimmed.isEmpty {
                    result.append(.inline(trimmed))
                }
            } else {
                if !comp.isEmpty {
                    result.append(.text(comp))
                }
            }
        }
        return result
    }
}

public struct DisplayMathView: View {
    let latex: String
    let isBlock: Bool

    public init(_ latex: String, isBlock: Bool = true) {
        self.latex = latex
        self.isBlock = isBlock
    }

    public var body: some View {
        if isBlock {
            HStack {
                Spacer()
                Text(latex)
                    .font(.system(size: 13, weight: .medium, design: .serif))
                    .italic()
                    .foregroundColor(Color.cyan)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .background(Color.cyan.opacity(0.08))
                    .cornerRadius(8)
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(Color.cyan.opacity(0.2), lineWidth: 1)
                    )
                Spacer()
            }
            .padding(.vertical, 4)
        } else {
            Text(latex)
                .font(.system(size: 12, weight: .medium, design: .serif))
                .italic()
                .foregroundColor(Color.cyan)
                .padding(.horizontal, 4)
                .padding(.vertical, 1)
                .background(Color.cyan.opacity(0.1))
                .cornerRadius(3)
        }
    }
}
