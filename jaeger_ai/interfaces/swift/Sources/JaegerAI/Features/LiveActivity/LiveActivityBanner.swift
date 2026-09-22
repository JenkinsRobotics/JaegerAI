//
//  LiveActivityBanner.swift
//  JaegerAI / Features / LiveActivity
//
//  Desktop equivalent of iOS Dynamic Island & Lock Screen Live Activities.
//  Presents active agent run state, pulsing telemetry, elapsed timer, and stop controls.
//

import SwiftUI
import Combine

public enum DesktopAgentPhase: String, Sendable {
    case idle = "Idle"
    case starting = "Starting"
    case thinking = "Reasoning"
    case usingTool = "Executing Tool"
    case generating = "Replying"

    public var color: Color {
        switch self {
        case .idle: return Color.gray
        case .starting: return Color.blue
        case .thinking: return Color.purple
        case .usingTool: return Color.orange
        case .generating: return Color.green
        }
    }

    public var icon: String {
        switch self {
        case .idle: return "pause.circle"
        case .starting: return "play.circle.fill"
        case .thinking: return "brain.head.profile"
        case .usingTool: return "gearshape.arrow.triangle.2.circlepath"
        case .generating: return "text.bubble.fill"
        }
    }
}

public struct LiveActivityBanner: View {
    let agentName: String
    let phase: DesktopAgentPhase
    let activityText: String
    let startedAt: Date
    let onStop: (() -> Void)?

    @State private var elapsedSeconds: Int = 0
    @State private var timer: AnyCancellable? = nil
    @State private var pulse: Bool = false

    public init(
        agentName: String = "Jaeger",
        phase: DesktopAgentPhase = .thinking,
        activityText: String = "Analyzing workspace and planning tool execution...",
        startedAt: Date = Date(),
        onStop: (() -> Void)? = nil
    ) {
        self.agentName = agentName
        self.phase = phase
        self.activityText = activityText
        self.startedAt = startedAt
        self.onStop = onStop
    }

    private var formattedTime: String {
        let mins = elapsedSeconds / 60
        let secs = elapsedSeconds % 60
        return String(format: "%02d:%02d", mins, secs)
    }

    public var body: some View {
        HStack(spacing: 10) {
            // Pulsing Live Indicator
            ZStack {
                Circle()
                    .fill(phase.color.opacity(pulse ? 0.35 : 0.15))
                    .frame(width: 22, height: 22)
                Circle()
                    .fill(phase.color)
                    .frame(width: 8, height: 8)
            }
            .animation(.easeInOut(duration: 1.0).repeatForever(autoreverses: true), value: pulse)
            .onAppear { pulse = true }

            // Phase and live activity description
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(agentName)
                        .font(.system(size: 11, weight: .bold))
                        .foregroundColor(Term.ink)

                    Text("·")
                        .font(.system(size: 11))
                        .foregroundColor(Term.inkDim)

                    HStack(spacing: 4) {
                        Image(systemName: phase.icon)
                            .font(.system(size: 9))
                        Text(phase.rawValue.uppercased())
                            .font(.system(size: 9, weight: .heavy, design: .monospaced))
                    }
                    .foregroundColor(phase.color)
                    .padding(.horizontal, 5)
                    .padding(.vertical, 1)
                    .background(phase.color.opacity(0.15))
                    .cornerRadius(3)
                }

                Text(activityText)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(Term.inkDim)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }

            Spacer()

            // Elapsed Timer
            Text(formattedTime)
                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                .foregroundColor(Term.ink)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(Color.white.opacity(0.08))
                .cornerRadius(4)

            // Stop / Abort button
            if let onStop {
                Button(action: onStop) {
                    Image(systemName: "stop.circle.fill")
                        .font(.system(size: 14))
                        .foregroundColor(Color.red.opacity(0.85))
                }
                .buttonStyle(.plain)
                .help("Cancel active run")
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Color(red: 0.08, green: 0.09, blue: 0.12))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(phase.color.opacity(0.35), lineWidth: 1)
        )
        .shadow(color: phase.color.opacity(0.12), radius: 6, x: 0, y: 2)
        .onAppear {
            elapsedSeconds = max(0, Int(Date().timeIntervalSince(startedAt)))
            timer = Timer.publish(every: 1.0, on: .main, in: .common)
                .autoconnect()
                .sink { _ in
                    elapsedSeconds = max(0, Int(Date().timeIntervalSince(startedAt)))
                }
        }
        .onDisappear {
            timer?.cancel()
        }
    }
}
