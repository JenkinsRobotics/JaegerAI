/// Global hotkey choice for JaegerShell, read from the Info.plist key `JaegerHotkey`.
/// Supported: "opt-space" (⌥Space) and "ctrl-opt-space" (⌃⌥Space). A missing or
/// unknown value falls back to ⌥Space and returns a note for the log.
public struct HotkeySpec: Equatable, Sendable {
    public let name: String
    public let label: String
    /// Carbon virtual key code (kVK_Space = 49).
    public let keyCode: UInt32
    /// Carbon modifier mask (cmdKey 256, shiftKey 512, optionKey 2048, controlKey 4096).
    public let modifiers: UInt32
}

public enum HotkeyConfig {
    public static let infoPlistKey = "JaegerHotkey"
    public static let optionSpace = HotkeySpec(name: "opt-space", label: "⌥Space", keyCode: 49, modifiers: 2048)
    public static let controlOptionSpace = HotkeySpec(
        name: "ctrl-opt-space", label: "⌃⌥Space", keyCode: 49, modifiers: 2048 | 4096)

    public static func resolve(_ raw: String?) -> (spec: HotkeySpec, note: String?) {
        guard let raw else { return (optionSpace, "\(infoPlistKey) missing; using ⌥Space") }
        switch raw.trimmingCharacters(in: .whitespaces).lowercased() {
        case "opt-space", "option-space": return (optionSpace, nil)
        case "ctrl-opt-space", "control-option-space": return (controlOptionSpace, nil)
        default: return (optionSpace, "unknown \(infoPlistKey) '\(raw)'; using ⌥Space")
        }
    }
}
