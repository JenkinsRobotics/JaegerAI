//
//  SlashRouting.swift
//  JaegerAI / ChatWindow
//
//  Windowed slash-command routing — Hermes-style. Bare ``/model`` (and
//  ``/models``) open a clickable picker overlay instead of dumping a
//  catalogue into the transcript. Typed ``/model use <provider> <name>``
//  is a direct switch. Pure data: unit-testable without a live bridge.
//

import Foundation

enum SlashRouting {

    struct Item: Identifiable, Equatable {
        var id: String { name }
        let name: String
        let summary: String
        var opensPicker: Bool { name == "model" || name == "models" }
    }

    /// What the composer should do with a submitted line. Pure — the
    /// view-model applies these; this type does not talk to the bridge.
    enum Action: Equatable {
        case modelPicker
        case modelUse(provider: String, model: String)
        case newChat
        case stop
        case steer(String)
        /// Send ``prompt`` as a real agent turn. ``display`` is what the
        /// user bubble shows (the typed slash line, when rewritten).
        case chat(prompt: String, display: String)
        case local(String)
        /// Slash or plain text — send the original line to the bridge.
        case passThrough
    }

    /// Commands the composer palette lists when the operator types ``/``.
    static let palette: [Item] = [
        Item(name: "goal",      summary: "run this job until it is genuinely done"),
        Item(name: "auto",      summary: "already on — send the task, it keeps going"),
        Item(name: "plan",      summary: "plan, then execute the objective"),
        Item(name: "deepthink", summary: "deep reasoning pass on a hard task"),
        Item(name: "compact",   summary: "compact conversation context"),
        Item(name: "board",     summary: "view task board and active cards"),
        Item(name: "tools",     summary: "list active tools and capabilities"),
        Item(name: "skills",    summary: "list available recipe skills"),
        Item(name: "facts",     summary: "inspect persistent memory facts"),
        Item(name: "model",     summary: "switch the agent's brain (picker overlay)"),
        Item(name: "mode",      summary: "this app already keeps going until done"),
        Item(name: "steer",     summary: "guide an in-flight autonomous run"),
        Item(name: "stop",      summary: "cancel active turn or autonomous loop"),
        Item(name: "copy",      summary: "copy the last reply to clipboard"),
        Item(name: "new",       summary: "start a new conversation"),
        Item(name: "help",      summary: "list all available slash commands"),
    ]

    /// True for ``/model`` / ``/models`` with no extra arguments.
    static func isBareModelPicker(_ text: String) -> Bool {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasPrefix("/") else { return false }
        let parts = trimmed.dropFirst()
            .split(whereSeparator: { $0.isWhitespace })
            .map(String.init)
        guard let head = parts.first else { return false }
        return ["model", "models"].contains(head.lowercased()) && parts.count == 1
    }

    /// ``/model use <provider> <model…>`` → the pair, else nil.
    static func modelUseArgs(_ text: String) -> (provider: String, model: String)? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasPrefix("/") else { return nil }
        let parts = trimmed.dropFirst()
            .split(whereSeparator: { $0.isWhitespace })
            .map(String.init)
        guard parts.count >= 4,
              parts[0].lowercased() == "model",
              parts[1].lowercased() == "use"
        else { return nil }
        let provider = parts[2]
        let model = parts[3...].joined(separator: " ")
        guard !provider.isEmpty, !model.isEmpty else { return nil }
        return (provider, model)
    }

    /// Map a picker slug onto ``configure_model``'s provider vocabulary.
    /// MLX is an in-process backend, not a separate endpoint.
    static func configureProvider(_ slug: String) -> String {
        switch slug.lowercased() {
        case "mlx", "llama-cpp", "llamacpp", "jaeger": return "local"
        case "lm-studio": return "lmstudio"
        default: return slug.lowercased()
        }
    }

    /// Palette rows whose name starts with the typed prefix after ``/``.
    /// Empty once the operator has typed a space (they're into args).
    static func matchingPalette(_ text: String) -> [Item] {
        guard text.hasPrefix("/") else { return [] }
        let body = String(text.dropFirst())
        if body.contains(" ") { return [] }
        let prefix = body.lowercased()
        return palette.filter { $0.name.hasPrefix(prefix) }
    }

    /// Split ``/name rest…`` into a lowercased name and the remainder.
    static func slashParts(_ text: String) -> (name: String, rest: String)? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasPrefix("/") else { return nil }
        let body = trimmed.dropFirst()
        let parts = body.split(maxSplits: 1, whereSeparator: { $0.isWhitespace })
        guard let head = parts.first, !head.isEmpty else { return nil }
        let rest = parts.count > 1
            ? String(parts[1]).trimmingCharacters(in: .whitespacesAndNewlines)
            : ""
        return (String(head).lowercased(), rest)
    }

    /// Map a submitted composer line onto a windowed action.
    ///
    /// ``/goal <job>`` is a real turn (the bridge keeps going until the
    /// work is done). Bare ``/goal`` and ``/auto`` are local notices —
    /// they must not bounce off the bridge as "TUI only".
    static func action(for text: String) -> Action {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if isBareModelPicker(trimmed) { return .modelPicker }
        if let use = modelUseArgs(trimmed) {
            return .modelUse(provider: use.provider, model: use.model)
        }
        guard let parts = slashParts(trimmed) else { return .passThrough }
        switch parts.name {
        case "goal":
            if parts.rest.isEmpty {
                return .local("Usage: /goal <what to finish>. Example: /goal improve Apple Notes structure and quality")
            }
            return .chat(prompt: parts.rest, display: trimmed)
        case "plan":
            if parts.rest.isEmpty {
                return .local("Usage: /plan <objective>")
            }
            return .chat(
                prompt: "Make a structured plan, then execute it:\n\n\(parts.rest)",
                display: trimmed
            )
        case "deepthink":
            if parts.rest.isEmpty {
                return .local("Usage: /deepthink <hard problem>")
            }
            return .chat(prompt: parts.rest, display: trimmed)
        case "auto", "mode":
            return .local("Autonomous continuation is already on. Send the task as a normal message — the engine keeps going until the work is done.")
        case "stop":
            return .stop
        case "steer":
            if parts.rest.isEmpty {
                return .local("Usage: /steer <guidance for the in-flight run>")
            }
            return .steer(parts.rest)
        case "new":
            return .newChat
        default:
            return .passThrough
        }
    }
}
