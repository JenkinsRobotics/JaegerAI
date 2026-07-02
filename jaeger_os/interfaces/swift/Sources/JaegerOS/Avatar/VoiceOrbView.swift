//
//  VoiceOrbView.swift
//  JaegerOS / Avatar
//
//  The agent's face inside a reactive voice-spectrum ring — the Swift twin of
//  the PySide6 ``avatar_player/voice_orb.py``. Three states:
//    * thinking (agent busy)   → a travelling wave-gradient around the ring
//    * speaking (TTS active)   → the ring's bars react (proxy envelope; Apple
//                                TTS gives no amplitude tap, matching the
//                                PySide6 proxy fallback)
//    * idle                    → a slow breathing ring
//  Colours run cyan (left) → pink (right), like the reference orb.
//

import AppKit
import SwiftUI

struct VoiceOrbView: View {
    @ObservedObject var agent: AgentBridge
    @ObservedObject private var tts = TTSManager.shared
    @ObservedObject private var pill = PillBridge.shared

    private let bars = 72

    var body: some View {
        TimelineView(.animation) { tl in
            Canvas { ctx, size in
                render(ctx, size, t: tl.date.timeIntervalSinceReferenceDate)
            }
        }
        .frame(minWidth: 240, minHeight: 240)
    }

    private func render(_ ctx: GraphicsContext, _ size: CGSize, t: Double) {
        let w = size.width, h = size.height
        let cx = w / 2, cy = h / 2
        let r = min(w, h) * 0.22
        let barMax = min(w, h) * 0.16
        let phase = t * 2.4
        let speaking = tts.isSpeaking
        let thinking = pill.isAgentBusy && !speaking

        // radial spectrum
        for i in 0..<bars {
            let a = Double(i) / Double(bars)
            let ang = a * 2 * .pi
            let val = barValue(a: a, phase: phase, speaking: speaking, thinking: thinking)
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

        // face circle (clipped) or a dark disc fallback
        let faceRect = CGRect(x: cx - r, y: cy - r, width: 2 * r, height: 2 * r)
        if let path = agent.status?.iconPath, let img = NSImage(contentsOfFile: path) {
            ctx.drawLayer { layer in
                layer.clip(to: Path(ellipseIn: faceRect))
                layer.draw(Image(nsImage: img), in: faceRect)
            }
        } else {
            ctx.fill(Path(ellipseIn: faceRect),
                     with: .color(Color(red: 0.05, green: 0.06, blue: 0.09)))
        }
        ctx.stroke(Path(ellipseIn: faceRect),
                   with: .color(Color(hue: 0.62, saturation: 0.4, brightness: 1.0, opacity: 0.5)),
                   lineWidth: 1.5)
    }

    private func barValue(a: Double, phase: Double, speaking: Bool, thinking: Bool) -> Double {
        if speaking {
            let env = 0.30 + 0.70 * abs(sin(a * .pi * 10 + phase * 1.4))
            let level = 0.55 + 0.35 * sin(phase * 3.1)      // proxy amplitude
            return max(0, level) * env
        } else if thinking {
            return 0.20 + 0.16 * (0.5 + 0.5 * sin(a * .pi * 6 + phase))
        }
        return 0.09 + 0.05 * (0.5 + 0.5 * sin(a * .pi * 4 + phase * 0.4))
    }
}
