// ShellPause.swift — pure logic for the status-item toggle and the shell-level Pause.
//
// Pause is shell-only: the global hotkey is unregistered, mic recording / speech stop, and the icon and
// status line show "Paused". It never touches the gateway, the WebUI or launchd (no stack pause API exists).

public enum WindowToggleAction: String, Sendable { case show, hide }

public enum WindowToggle {
    /// Status-item left click: a visible window hides, a hidden one shows. Focus no longer matters,
    /// because clicking an LSUIElement status item does not make the app active.
    public static func action(windowVisible: Bool) -> WindowToggleAction { windowVisible ? .hide : .show }
}

public struct ShellPauseState: Sendable, Equatable {
    public private(set) var paused = false
    public init() {}
    public var menuTitle: String { paused ? "Resume Jaeger Shell" : "Pause Jaeger Shell" }
    public var statusTitle: String { paused ? "Shell: paused (hotkey and voice off)" : "Shell: active" }
    /// Returns true if the state changed.
    @discardableResult public mutating func set(_ value: Bool) -> Bool {
        guard value != paused else { return false }
        paused = value
        return true
    }
}
