//
//  JaegerMechIcon.swift
//  JaegerOS
//
//  The Jaeger mech head — the JROS brand mark we landed on in the
//  gh-pages landing site. Drawn as a SwiftUI Shape (not bundled as an
//  asset) so it:
//
//    * scales perfectly at any menu-bar resolution
//    * fills with `.primary` and inherits the system's light/dark
//      menu-bar tint automatically (no template-image setup needed)
//    * adds zero binary weight to the .app bundle
//
//  Source SVG (from docs/index.html on the gh-pages branch):
//
//      <svg viewBox="0 0 32 32" fill="currentColor">
//        <rect x="8" y="10" width="16" height="14" rx="2"/>   body
//        <rect x="11" y="6" width="10" height="4" rx="1"/>    crown
//        <line x1="16" y1="3" x2="16" y2="6" stroke-width="2"/> antenna
//        <circle cx="16" cy="3" r="1.5"/>                     antenna dot
//        <circle cx="13" cy="15" r="1.8" fill="#0a0e14"/>     left eye  (cutout)
//        <circle cx="19" cy="15" r="1.8" fill="#0a0e14"/>     right eye (cutout)
//        <rect x="13" y="19" width="6" height="1.5" fill="#0a0e14"/>  mouth (cutout)
//      </svg>
//
//  The eyes + mouth are filled with the background color in the SVG to
//  read as "darker pixels"; in this Shape they're separate subpaths and
//  we use evenOdd fill so they punch through cleanly when the mech is
//  rendered against the menu bar's varying backgrounds.
//

import SwiftUI

/// The Jaeger mech head as a single Path with eye+mouth cutouts.
///
/// Render with `.fill(style: FillStyle(eoFill: true))` so the cutouts
/// punch through. SwiftUI's default fill style is even-odd-aware when
/// `FillStyle(eoFill: true)` is requested.
struct JaegerMechShape: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        // Maintain a 32x32 design grid regardless of render size; scale
        // everything off the smaller of (width, height) so a non-square
        // bounding rect still draws a centered square mech.
        let s = min(rect.width, rect.height) / 32
        let xOffset = (rect.width  - 32 * s) / 2
        let yOffset = (rect.height - 32 * s) / 2

        // Convenience to translate the 32x32 design coords into the
        // shape's actual coordinate space.
        func r(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat) -> CGRect {
            CGRect(x: xOffset + x * s, y: yOffset + y * s, width: w * s, height: h * s)
        }

        // ── outer (mech body parts — filled) ──────────────────────
        // Body. 16x14 with rx=2.
        path.addRoundedRect(in: r(8, 10, 16, 14),
                            cornerSize: CGSize(width: 2 * s, height: 2 * s))
        // Crown. 10x4 with rx=1.
        path.addRoundedRect(in: r(11, 6, 10, 4),
                            cornerSize: CGSize(width: 1 * s, height: 1 * s))
        // Antenna stem (the SVG was a stroked line; render as a 2-wide
        // rect so the path stays a single fill, no separate stroke).
        path.addRect(r(15, 3, 2, 3))
        // Antenna tip dot. Centered at (16, 3), r=1.5 → 3x3 ellipse.
        path.addEllipse(in: r(14.5, 1.5, 3, 3))

        // ── cutouts (with evenOdd, these become holes) ────────────
        // Left eye, centered at (13, 15), r=1.8 → 3.6x3.6 ellipse.
        path.addEllipse(in: r(11.2, 13.2, 3.6, 3.6))
        // Right eye, centered at (19, 15), r=1.8 → 3.6x3.6 ellipse.
        path.addEllipse(in: r(17.2, 13.2, 3.6, 3.6))
        // Mouth strip.
        path.addRect(r(13, 19, 6, 1.5))

        return path
    }
}

/// Drop-in view that renders the mech head at a fixed menu-bar size,
/// filled with the current foreground style so it adapts to light/dark
/// menu bars without any template-image setup.
struct JaegerMechIcon: View {
    var size: CGFloat = 18

    var body: some View {
        JaegerMechShape()
            .fill(style: FillStyle(eoFill: true))
            .frame(width: size, height: size)
    }
}

#Preview {
    HStack(spacing: 24) {
        JaegerMechIcon()                       // menu-bar size
        JaegerMechIcon(size: 64)               // medium
        JaegerMechIcon(size: 128)              // large
    }
    .padding()
}
