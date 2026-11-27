// JaegerShellCore: what the native window is and what it exposes to the page (Jenkins Robotics, 2026-10-17).
// Geometry/colours follow the measured Grok Bot desktop window (Jaeger-Mac-App-Improvement-Guide.md): a solid
// #fcfcfc / #121212 window (no vibrancy), a 52 pt top band, traffic lights at x16 / y15, 1040×760 default and
// 600×520 minimum. Original implementation; no third-party code.
import Foundation

public enum NativeChromeContract {
    public static let hostAttribute = "data-jaeger-host"
    public static let hostValue = "macos"
    /// Kept for the page: "none" now — the window is solid, nothing translucent sits behind the page.
    public static let vibrancyAttribute = "data-native-vibrancy"
    public static let vibrancyValue = "none"
    public static let titlebarHeightVar = "--jaeger-native-titlebar-height"
    public static let trafficLightWidthVar = "--jaeger-native-traffic-light-width"
    /// The page's top band (sidebar header / chat band) height.
    public static let bandHeightVar = "--jaeger-native-band-height"
    /// Horizontal space the page keeps clear on the left of the band for the traffic lights.
    public static let trafficLightReserveVar = "--jaeger-native-traffic-light-reserve"
    /// StudioWindowChrome's drag handler (AetherStudio contract): mousedown inside this attribute drags the window.
    public static let dragRegionAttribute = "data-aether-window-drag-region"

    public static let defaultWidth: Double = 1040
    public static let defaultHeight: Double = 760
    public static let minWidth: Double = 600
    public static let minHeight: Double = 520
    public static let bandHeight: Double = 52
    /// Close button's top-left corner, in window coordinates measured from the top-left.
    public static let trafficLightX: Double = 16
    public static let trafficLightY: Double = 15
    /// Left edge to left edge of neighbouring buttons. Measured on the reference window: 14 pt lights at
    /// x 16 / 39 / 62 (AppKit's own spacing is 20 pt).
    public static let trafficLightPitch: Double = 23
    /// Gap after the zoom button before page content may start.
    public static let trafficLightReserveGap: Double = 12

    public struct RGB: Equatable, Sendable {
        public let r: UInt8, g: UInt8, b: UInt8
        public init(_ r: UInt8, _ g: UInt8, _ b: UInt8) { self.r = r; self.g = g; self.b = b }
        public var hex: String { String(format: "#%02x%02x%02x", r, g, b) }
        public static func parse(hex: String) -> RGB? {
            let s = hex.hasPrefix("#") ? String(hex.dropFirst()) : hex
            guard s.count == 6, let v = UInt32(s, radix: 16) else { return nil }
            return RGB(UInt8((v >> 16) & 0xff), UInt8((v >> 8) & 0xff), UInt8(v & 0xff))
        }
    }
    public static let backgroundLight = RGB(0xfc, 0xfc, 0xfc)
    public static let backgroundDark = RGB(0x12, 0x12, 0x12)
    public static func background(dark: Bool) -> RGB { dark ? backgroundDark : backgroundLight }

    /// A rectangle in window coordinates with a top-left origin.
    public struct Rect: Equatable, Sendable {
        public var x: Double, top: Double, width: Double, height: Double
        public init(x: Double, top: Double, width: Double, height: Double) {
            self.x = x; self.top = top; self.width = width; self.height = height
        }
        public var maxX: Double { x + width }
    }

    /// Places the traffic lights in a row: close at (trafficLightX, trafficLightY), each next one
    /// trafficLightPitch further right; sizes stay AppKit's.
    public static func trafficLightTargets(_ frames: [Rect]) -> [Rect] {
        frames.enumerated().map { i, f in
            Rect(x: trafficLightX + Double(i) * trafficLightPitch, top: trafficLightY, width: f.width, height: f.height)
        }
    }

    /// Reserve for the page: right edge of the zoom button plus the gap; 0 when the buttons are hidden.
    public static func trafficLightReserve(zoomMaxX: Double?) -> Double {
        guard let zoomMaxX, zoomMaxX > 0 else { return 0 }
        return zoomMaxX + trafficLightReserveGap
    }

    static func px(_ value: Double) -> String { "\(Int(value.rounded()))px" }

    public static func values(titlebarHeight: Double, trafficLightWidth: Double,
                              bandHeight: Double = NativeChromeContract.bandHeight,
                              trafficLightReserve: Double = 0) -> [String: String] {
        [hostAttribute: hostValue, vibrancyAttribute: vibrancyValue,
         titlebarHeightVar: px(titlebarHeight), trafficLightWidthVar: px(trafficLightWidth),
         bandHeightVar: px(bandHeight), trafficLightReserveVar: px(trafficLightReserve)]
    }

    /// Runs at document start (and again on full-screen changes) on the main frame only.
    public static func script(titlebarHeight: Double, trafficLightWidth: Double,
                              bandHeight: Double = NativeChromeContract.bandHeight,
                              trafficLightReserve: Double = 0) -> String {
        """
        (() => {
          const d = document.documentElement;
          d.setAttribute('\(hostAttribute)', '\(hostValue)');
          d.setAttribute('\(vibrancyAttribute)', '\(vibrancyValue)');
          d.style.setProperty('\(titlebarHeightVar)', '\(px(titlebarHeight))');
          d.style.setProperty('\(trafficLightWidthVar)', '\(px(trafficLightWidth))');
          d.style.setProperty('\(bandHeightVar)', '\(px(bandHeight))');
          d.style.setProperty('\(trafficLightReserveVar)', '\(px(trafficLightReserve))');
        })();
        """
    }
}
