//
//  VoiceOrbView.swift
//  JaegerAI / Avatar
//
//  Voice ring: measured output RMS during playback, quiet while synthesis is
//  pending, and separate decorative idle/thinking animation. No synthetic
//  waveform is presented as an audio measurement.

import AppKit
import SwiftUI

/// The orb's animation state, derived from live bridge signals.
enum OrbState: Equatable {
    case idle, thinking, speaking
}

struct VoiceOrbView: View {
    @ObservedObject var agent: AgentBridge
    @ObservedObject private var tts = TTSManager.shared

    /// Crossfade bookkeeping — which state we came from and when the
    /// switch happened. Read by the render pass to blend bar targets.
    @State private var previous: OrbState = .idle
    @State private var changedAt: TimeInterval = 0

    /// The face image, decoded ONCE per icon path (not per frame).
    @State private var face: NSImage?
    @State private var facePath: String?

    private let bars = 72
    private let fadeSeconds = 0.35

    /// Live state off the bridge: TTS beats busy beats idle.
    private var current: OrbState {
        if tts.measuredAmplitude > 0.001 { return .speaking }
        if tts.isSpeaking { return .thinking }
        if agent.isBusy { return .thinking }
        return .idle
    }

    var body: some View {
        let state = current
        TimelineView(.animation(minimumInterval: state == .idle ? 1.0 / 20.0 : nil)) { tl in
            Canvas { ctx, size in
                render(ctx, size, state: state,
                       t: tl.date.timeIntervalSinceReferenceDate)
            }
        }
        .frame(minWidth: 240, minHeight: 240)
        .onChange(of: state) { old, _ in
            previous = old
            changedAt = Date.timeIntervalSinceReferenceDate
        }
        .onChange(of: agent.status?.iconPath) { _, path in loadFace(path) }
        .onAppear { loadFace(agent.status?.iconPath) }
        .accessibilityLabel(Text("Voice orb — \(label(for: state)); measured playback level"))
    }

    private func label(for state: OrbState) -> String {
        switch state {
        case .idle: return "standing by"
        case .thinking: return "thinking"
        case .speaking: return "speaking"
        }
    }

    private func loadFace(_ path: String?) {
        guard path != facePath else { return }
        facePath = path
        face = path.flatMap { NSImage(contentsOfFile: $0) }
    }

    // MARK: - render

    private func render(_ ctx: GraphicsContext, _ size: CGSize,
                        state: OrbState, t: Double) {
        let w = size.width, h = size.height
        let cx = w / 2, cy = h / 2
        let r = min(w, h) * 0.22
        let barMax = min(w, h) * 0.16
        let phase = t * 2.4
        // Crossfade factor: 0 = fully previous state, 1 = fully current.
        let blend = min(1.0, max(0.0, (t - changedAt) / fadeSeconds))

        // radial spectrum
        for i in 0..<bars {
            let a = Double(i) / Double(bars)
            let ang = a * 2 * .pi
            let from = barValue(a: a, phase: phase, state: previous)
            let to = barValue(a: a, phase: phase, state: state)
            let val = from + (to - from) * blend
            let r0 = r + 8
            let r1 = r0 + CGFloat(val) * barMax
            var p = Path()
            p.move(to: CGPoint(x: cx + CGFloat(cos(ang)) * r0, y: cy + CGFloat(sin(ang)) * r0))
            p.addLine(to: CGPoint(x: cx + CGFloat(cos(ang)) * r1, y: cy + CGFloat(sin(ang)) * r1))
            let hue = (190.0 + 135.0 * (0.5 + 0.5 * cos(ang))) / 360.0   // cyan→pink
            let alpha = 0.35 + 0.6 * min(1.0, val * 2.2)
            ctx.stroke(p, with: .color(Color(hue: hue, saturation: 0.82, brightness: 1.0,
                                             opacity: alpha)),
                       style: StrokeStyle(lineWidth: 2.4, lineCap: .round))
        }

        // face circle (clipped) or a dark disc + mic glyph fallback —
        // same fallback the PySide6 orb draws.
        let faceRect = CGRect(x: cx - r, y: cy - r, width: 2 * r, height: 2 * r)
        if let face {
            ctx.drawLayer { layer in
                layer.clip(to: Path(ellipseIn: faceRect))
                layer.draw(Image(nsImage: face), in: faceRect)
            }
        } else {
            ctx.fill(Path(ellipseIn: faceRect),
                     with: .color(Color(red: 0.05, green: 0.06, blue: 0.09)))
            var mic = ctx.resolve(Image(systemName: "mic.fill"))
            mic.shading = .color(Color(hue: 0.53, saturation: 0.6, brightness: 1.0))
            let side = r * 0.7
            ctx.draw(mic, in: CGRect(x: cx - side / 2, y: cy - side / 2,
                                     width: side, height: side))
        }
        ctx.stroke(Path(ellipseIn: faceRect),
                   with: .color(Color(hue: 0.62, saturation: 0.4, brightness: 1.0, opacity: 0.5)),
                   lineWidth: 1.5)
    }

    /// Procedural per-bar target for one state — the Swift echo of the
    /// PySide6 orb's ``_tick`` targets.
    private func barValue(a: Double, phase: Double, state: OrbState) -> Double {
        switch state {
        case .speaking:
            return tts.measuredAmplitude
        case .thinking:
            return 0.20 + 0.16 * (0.5 + 0.5 * sin(a * .pi * 6 + phase))
        case .idle:
            return 0.09 + 0.05 * (0.5 + 0.5 * sin(a * .pi * 4 + phase * 0.4))
        }
    }
}
