//
//  VoiceOrbView.swift
//  JaegerOS / Avatar
//
//  The agent's face inside a reactive voice-spectrum ring — the Swift twin of
//  the PySide6 ``avatar_player/voice_orb.py``. Three states:
//    * speaking (TTS active)   → the ring's bars react (proxy envelope; Apple
//                                TTS exposes no amplitude tap, matching the
//                                PySide6 proxy fallback — real amplitude over
//                                the bridge is the noted follow-up)
//    * thinking (agent busy)   → a travelling wave-gradient around the ring
//    * idle                    → a slow breathing ring
//  Colours run cyan (left) → pink (right), like the reference orb.
//
//  Rendering: TimelineView + Canvas, no timers. The schedule drops to 20 fps
//  while idle (breathing needs no more) and runs at display rate only while
//  speaking/thinking. State switches crossfade over ~0.35 s — the Canvas is
//  stateless, so instead of the Qt orb's per-bar exponential smoothing we
//  blend the previous state's procedural target into the new one.
//

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
        if tts.isSpeaking { return .speaking }
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
        .accessibilityLabel(Text("Voice orb — \(label(for: state))"))
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
            // Proxy waveform while Apple TTS plays (no amplitude tap).
            let env = 0.30 + 0.70 * abs(sin(a * .pi * 10 + phase * 1.4))
            let level = 0.55 + 0.35 * sin(phase * 3.1)
            return max(0, level) * env
        case .thinking:
            return 0.20 + 0.16 * (0.5 + 0.5 * sin(a * .pi * 6 + phase))
        case .idle:
            return 0.09 + 0.05 * (0.5 + 0.5 * sin(a * .pi * 4 + phase * 0.4))
        }
    }
}
