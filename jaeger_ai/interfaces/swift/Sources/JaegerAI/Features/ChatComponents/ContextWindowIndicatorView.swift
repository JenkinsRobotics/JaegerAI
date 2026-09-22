//
//  ContextWindowIndicatorView.swift
//  JaegerAI / Features / ChatComponents
//
//  Context window usage gauge and token breakdown ported from Hermex.
//

import SwiftUI

public struct ContextWindowSnapshot: Sendable {
    public let usedTokens: Int
    public let maxTokens: Int

    public init(usedTokens: Int = 18420, maxTokens: Int = 131072) {
        self.usedTokens = usedTokens
        self.maxTokens = max(1, maxTokens)
    }

    public var percentage: Double {
        Double(usedTokens) / Double(maxTokens)
    }

    public var percentageLabel: String {
        "\(Int(percentage * 100))%"
    }

    public var isCompactionAdvised: Bool {
        percentage >= 0.75
    }
}

public struct ContextWindowIndicatorView: View {
    public let snapshot: ContextWindowSnapshot
    @State private var showPopover = false

    public init(snapshot: ContextWindowSnapshot = ContextWindowSnapshot()) {
        self.snapshot = snapshot
    }

    private var progressColor: Color {
        let pct = snapshot.percentage
        if pct < 0.50 { return Color.green }
        if pct < 0.75 { return Color.yellow }
        if pct < 0.90 { return Color.orange }
        return Color.red
    }

    public var body: some View {
        Button {
            showPopover.toggle()
        } label: {
            ZStack {
                // Background Track
                Circle()
                    .stroke(Color.white.opacity(0.1), lineWidth: 2.5)
                    .frame(width: 26, height: 26)

                // Progress Arc
                Circle()
                    .trim(from: 0, to: CGFloat(min(snapshot.percentage, 1.0)))
                    .stroke(
                        progressColor,
                        style: StrokeStyle(lineWidth: 2.5, lineCap: .round)
                    )
                    .frame(width: 26, height: 26)
                    .rotationEffect(.degrees(-90))

                // Percentage Text
                Text(snapshot.percentageLabel)
                    .font(.system(size: 8, weight: .bold, design: .monospaced))
                    .foregroundColor(Term.ink)
            }
        }
        .buttonStyle(.plain)
        .help("Context Window Usage")
        .popover(isPresented: $showPopover, arrowEdge: .top) {
            contextPopoverContent
        }
    }

    private var contextPopoverContent: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Context Window")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundColor(Term.ink)
                Spacer()
                Text(snapshot.percentageLabel)
                    .font(.system(size: 12, weight: .heavy, design: .monospaced))
                    .foregroundColor(progressColor)
            }

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text("Used Tokens:")
                        .font(.system(size: 11))
                        .foregroundColor(Term.inkDim)
                    Spacer()
                    Text("\(snapshot.usedTokens.formatted())")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundColor(Term.ink)
                }

                HStack {
                    Text("Maximum Limit:")
                        .font(.system(size: 11))
                        .foregroundColor(Term.inkDim)
                    Spacer()
                    Text("\(snapshot.maxTokens.formatted())")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundColor(Term.ink)
                }
            }

            if snapshot.isCompactionAdvised {
                HStack(spacing: 6) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.system(size: 11))
                        .foregroundColor(.orange)
                    Text("High token usage. Compaction recommended.")
                        .font(.system(size: 10))
                        .foregroundColor(.orange)
                }
                .padding(6)
                .background(Color.orange.opacity(0.12))
                .cornerRadius(4)
            }
        }
        .padding(14)
        .frame(width: 240)
        .background(Color(red: 0.10, green: 0.11, blue: 0.14))
    }
}
