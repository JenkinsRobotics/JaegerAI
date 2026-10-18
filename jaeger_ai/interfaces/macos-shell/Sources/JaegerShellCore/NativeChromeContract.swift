// JaegerShellCore: what the native window exposes to the page (Jenkins Robotics, 2026-10-17).
import Foundation

public enum NativeChromeContract {
    public static let hostAttribute = "data-jaeger-host"
    public static let hostValue = "macos"
    public static let vibrancyAttribute = "data-native-vibrancy"
    public static let vibrancyValue = "sidebar"
    public static let titlebarHeightVar = "--jaeger-native-titlebar-height"
    public static let trafficLightWidthVar = "--jaeger-native-traffic-light-width"
    /// StudioWindowChrome's drag handler (AetherStudio contract): mousedown inside this attribute drags the window.
    public static let dragRegionAttribute = "data-aether-window-drag-region"
    public static let minWidth: Double = 860
    public static let minHeight: Double = 560

    static func px(_ value: Double) -> String { "\(Int(value.rounded()))px" }

    public static func values(titlebarHeight: Double, trafficLightWidth: Double) -> [String: String] {
        [hostAttribute: hostValue, vibrancyAttribute: vibrancyValue,
         titlebarHeightVar: px(titlebarHeight), trafficLightWidthVar: px(trafficLightWidth)]
    }

    /// Runs at document start (and again on full-screen changes) on the main frame only.
    public static func script(titlebarHeight: Double, trafficLightWidth: Double) -> String {
        """
        (() => {
          const d = document.documentElement;
          d.setAttribute('\(hostAttribute)', '\(hostValue)');
          d.setAttribute('\(vibrancyAttribute)', '\(vibrancyValue)');
          d.style.setProperty('\(titlebarHeightVar)', '\(px(titlebarHeight))');
          d.style.setProperty('\(trafficLightWidthVar)', '\(px(trafficLightWidth))');
        })();
        """
    }
}
