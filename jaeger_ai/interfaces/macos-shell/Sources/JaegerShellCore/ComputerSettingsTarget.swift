import Foundation

/// Fixed OS navigation targets; opening a pane never changes a permission.
public enum ComputerSettingsTarget: String, Equatable, Sendable {
    case accessibility
    case screenRecording = "screen_recording"
    public var url: URL {
        let anchor = self == .accessibility ? "Privacy_Accessibility" : "Privacy_ScreenCapture"
        return URL(string: "x-apple.systempreferences:com.apple.preference.security?" + anchor)!
    }
}
