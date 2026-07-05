//
//  SplashWindow.swift
//  JaegerOS
//
//  Startup splash for the native Swift app. It shows the boot sequence while
//  the bridge, settings cache, and hotkey layer come online.
//

import AppKit
import SwiftUI

@MainActor
final class SplashWindowController {
    static let shared = SplashWindowController()

    private let model = SplashBootModel()
    private var window: NSWindow?

    private init() {}

    func show() {
        if window != nil { return }

        let view = SplashWindowView(model: model)
        let hosting = NSHostingView(rootView: view)
        let panel = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 780, height: 540),
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        panel.contentView = hosting
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.isMovableByWindowBackground = true
        panel.level = .floating
        panel.center()
        panel.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        window = panel
    }

    func start(_ id: String, _ title: String, detail: String, progress: Double) {
        model.start(id, title, detail: detail, progress: progress)
    }

    func complete(_ id: String, detail: String, progress: Double) {
        model.complete(id, detail: detail, progress: progress)
    }

    func fail(_ id: String, detail: String, progress: Double) {
        model.fail(id, detail: detail, progress: progress)
    }

    func finish(_ detail: String) async {
        model.finish(detail)
        // Hold the SYSTEM ONLINE state long enough to actually read it
        // before the window fades — the boot earned its victory lap.
        try? await Task.sleep(nanoseconds: 1_800_000_000)
        window?.orderOut(nil)
        window = nil
    }
}

private enum SplashPhase {
    case pending, running, done, failed
}

private struct SplashStage: Identifiable {
    let id: String
    var title: String
    var detail: String
    var phase: SplashPhase = .pending
}

@MainActor
private final class SplashBootModel: ObservableObject {
    @Published var headline = "Booting JaegerOS"
    @Published var detail = "Initializing JROS runtime"
    @Published var progress = 0.04
    @Published var stages: [SplashStage] = []

    func start(_ id: String, _ title: String, detail: String, progress: Double) {
        upsert(id, title, detail: detail, phase: .running)
        headline = title
        self.detail = detail
        self.progress = progress
    }

    func complete(_ id: String, detail: String, progress: Double) {
        set(id, detail: detail, phase: .done)
        self.detail = detail
        self.progress = progress
    }

    func fail(_ id: String, detail: String, progress: Double) {
        set(id, detail: detail, phase: .failed)
        headline = "Continuing offline"
        self.detail = detail
        self.progress = progress
    }

    func finish(_ detail: String) {
        headline = "SYSTEM ONLINE"
        self.detail = detail
        progress = 1.0
    }

    private func upsert(_ id: String, _ title: String, detail: String, phase: SplashPhase) {
        if let index = stages.firstIndex(where: { $0.id == id }) {
            stages[index].title = title
            stages[index].detail = detail
            stages[index].phase = phase
        } else {
            stages.append(SplashStage(id: id, title: title, detail: detail, phase: phase))
        }
    }

    private func set(_ id: String, detail: String, phase: SplashPhase) {
        guard let index = stages.firstIndex(where: { $0.id == id }) else { return }
        stages[index].detail = detail
        stages[index].phase = phase
    }
}

private struct SplashWindowView: View {
    @ObservedObject var model: SplashBootModel

    var body: some View {
        ZStack(alignment: .bottom) {
            hero
            LinearGradient(
                colors: [.black.opacity(0.05), .black.opacity(0.28), .black.opacity(0.78)],
                startPoint: .top,
                endPoint: .bottom
            )
            VStack(spacing: 0) {
                Spacer()
                bootPanel
            }
        }
        .frame(width: 780, height: 540)
        .clipShape(RoundedRectangle(cornerRadius: 18))
        .overlay(RoundedRectangle(cornerRadius: 18)
            .stroke(Color.white.opacity(0.08), lineWidth: 1))
        .background(RoundedRectangle(cornerRadius: 18).fill(Color.black))
    }

    @ViewBuilder private var hero: some View {
        if let url = Bundle.module.url(forResource: "splash_hero", withExtension: "png"),
           let image = NSImage(contentsOf: url) {
            Image(nsImage: image)
                .resizable()
                .scaledToFill()
                .frame(width: 780, height: 540)
        } else {
            LinearGradient(
                colors: [
                    Color(red: 0.02, green: 0.02, blue: 0.06),
                    Color(red: 0.12, green: 0.07, blue: 0.20),
                    Color.black,
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        }
    }

    private var bootPanel: some View {
        HStack(alignment: .bottom, spacing: 24) {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 14) {
                    JaegerMechIcon(size: 46)
                    VStack(alignment: .leading, spacing: 0) {
                        Text("REAL-WORLD LOCAL AGENTIC AGENT FRAMEWORK")
                            .font(.system(size: 11, weight: .semibold))
                            .kerning(1.4)
                            .foregroundStyle(Color.white.opacity(0.65))
                        Text("JAEGER OS")
                            .font(.system(size: 36, weight: .heavy))
                            .foregroundStyle(.white)
                    }
                }
                Text(model.headline)
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(.white)
                Text(model.detail)
                    .font(.system(size: 12))
                    .foregroundStyle(Color.white.opacity(0.62))
                    .lineLimit(1)
                ProgressView(value: model.progress)
                    .progressViewStyle(.linear)
                    .tint(Color(red: 0.35, green: 0.95, blue: 0.70))
                    .frame(width: 310)
                // The fun line: robot humor rotating along the bottom
                // while the boot grinds — a new quip every few seconds
                // (frozen once the system is online).
                TimelineView(.periodic(from: .now, by: 4)) { context in
                    let idx = Int(context.date.timeIntervalSinceReferenceDate / 4)
                        % SplashQuips.all.count
                    Text(model.progress >= 1.0 ? "All systems nominal."
                                               : SplashQuips.all[idx])
                        .font(.system(size: 11, weight: .medium).italic())
                        .foregroundStyle(Color.white.opacity(0.45))
                        .lineLimit(1)
                        .animation(.easeInOut(duration: 0.4), value: idx)
                }
            }

            Spacer(minLength: 20)

            VStack(alignment: .leading, spacing: 7) {
                ForEach(model.stages) { stage in
                    stageRow(stage)
                }
            }
            .frame(width: 270, alignment: .leading)
        }
        .padding(EdgeInsets(top: 24, leading: 30, bottom: 24, trailing: 30))
        .background(.black.opacity(0.72))
    }

    private func stageRow(_ stage: SplashStage) -> some View {
        HStack(spacing: 9) {
            statusDot(stage.phase)
            VStack(alignment: .leading, spacing: 1) {
                Text(stage.title)
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(.white.opacity(stage.phase == .pending ? 0.42 : 0.88))
                Text(stage.detail)
                    .font(.system(size: 10))
                    .foregroundStyle(.white.opacity(0.45))
                    .lineLimit(1)
            }
        }
    }

    private func statusDot(_ phase: SplashPhase) -> some View {
        let color: Color = {
            switch phase {
            case .pending: return Color.white.opacity(0.22)
            case .running: return Color(red: 0.45, green: 0.78, blue: 1.0)
            case .done: return Color(red: 0.35, green: 0.95, blue: 0.70)
            case .failed: return Color(red: 1.0, green: 0.48, blue: 0.42)
            }
        }()
        return Circle()
            .fill(color)
            .frame(width: 8, height: 8)
            .shadow(color: color.opacity(0.55), radius: phase == .running ? 6 : 0)
    }
}

/// One line of robot-inspired humor per launch. Picked once at process
/// start so every stage of the same boot shows the same quip.
enum SplashQuips {
    static let all: [String] = [
        "Calibrating sarcasm servos…",
        "Warming up the thinking rocks.",
        "Charging personality capacitors.",
        "Reticulating splines. Again.",
        "Teaching sand to think.",
        "Do robots dream? Checking…",
        "Aligning giant-robot chakras.",
        "Oiling the metaphors.",
        "Counting to one in binary: 1.",
        "Assembling opinions… 87% done.",
        "Waking the ghost in the shell.",
        "Stretching the neural nets.",
        "Polishing the chrome dome.",
        "Rebooting my sense of humor.",
        "Spinning up the fun cortex.",
    ]
    static let pick: String = all.randomElement() ?? "Booting…"
}
