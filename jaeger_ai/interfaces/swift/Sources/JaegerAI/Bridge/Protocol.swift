//
//  Protocol.swift
//  JaegerAI / Bridge
//
//  Shared NDJSON value types + line framer for the stdio bridge. The bridge
//  speaks the JaegerAI client protocol (see jaeger_os/protocol.py +
//  dev/docs/JaegerAI_CLIENT_PROTOCOL.md); ``BridgeProcess`` parses the typed
//  frames itself. This file holds the small reusable pieces:
//
//    - ``Event``       — an inline activity event the AgentBridge fans out
//                        to ``ChatViewModel`` (thinking / tool chips).
//    - ``AnyDecodable`` — type-erased JSON value (Event payloads).
//    - ``FrameStream``  — splits a byte stream on '\n' into whole frames.
//
//  (The old socket-RPC Request/Response/NDJSON codec was removed with the
//  daemon — BridgeProcess reads NDJSON frames directly.)
//

import Foundation

/// An inline activity event surfaced during a turn (e.g. thinking,
/// tool.start / tool.complete). ``payload`` carries event-specific fields.
///
/// ``@unchecked Sendable`` is honest: the wrapped values come from
/// ``JSONSerialization`` (immutable Foundation types) and the struct is a
/// ``let``-only carrier.
struct Event: @unchecked Sendable {
    let name: String
    let payload: [String: AnyDecodable]
}

/// Type-erased JSON value — pull a typed value out with ``get(_:)``.
///
/// ``@unchecked Sendable`` is fine for the same reason as ``Event``: the
/// wrapped value is always a JSONSerialization-produced immutable type.
struct AnyDecodable: @unchecked Sendable {
    let value: Any

    init(_ value: Any) { self.value = value }

    /// Pull out the value if it is of the expected type, else nil.
    func get<T>(_ type: T.Type) -> T? { value as? T }
}

/// Stateful framer: append inbound bytes, get back whole NDJSON frames.
/// Partial frames buffer until a later ``feed`` completes them (pipe reads
/// aren't aligned to message boundaries).
final class FrameStream {
    private var buffer = Data()

    /// Append bytes; return any complete frames now parseable (no newline).
    func feed(_ chunk: Data) -> [Data] {
        buffer.append(chunk)
        var frames: [Data] = []
        while let nl = buffer.firstIndex(of: 0x0A) {
            let frame = buffer.subdata(in: buffer.startIndex..<nl)
            buffer.removeSubrange(buffer.startIndex...nl)
            if !frame.isEmpty { frames.append(frame) }
        }
        return frames
    }
}

// MARK: - Live task progress (work_ledger frames)

/// Structured snapshot of a long batch job, decoded from a ``tool``
/// frame whose ``name`` is ``work_ledger`` (or whose ``args`` carry
/// done/total). Additive — older cores that only send
/// ``detail: "worker 190/292"`` still parse.
struct ToolProgress: Sendable, Equatable {
    let taskId: String
    let taskName: String
    let done: Int
    let total: Int
    let remaining: Int
    let currentItem: String
    let completed: Bool
    let state: String
    let detail: String
    let step: Int?

    var fraction: Double {
        guard total > 0 else { return completed ? 1 : 0 }
        return min(1, max(0, Double(done) / Double(total)))
    }

    var countLabel: String {
        if total > 0 { return "\(done)/\(total)" }
        if completed { return "done" }
        if let step { return "step \(step)" }
        return "running"
    }

    var title: String {
        taskName.isEmpty ? "Task" : taskName
    }

    /// Best-effort parse. Returns nil when the frame is an ordinary
    /// tool chip with no ledger counts.
    static func parse(name: String, detail: String?,
                      args: [String: Any]?) -> ToolProgress? {
        let fromArgs = args.flatMap { Self.from(args: $0, fallbackDetail: detail) }
        if let fromArgs { return fromArgs }
        if name == "work_ledger" {
            return Self.from(detail: detail ?? "", name: name)
        }
        if let detail, detail.contains("/") {
            return Self.from(detail: detail, name: name)
        }
        return nil
    }

    private static func from(args: [String: Any],
                             fallbackDetail: String?) -> ToolProgress? {
        let done = intVal(args["done"])
        let total = intVal(args["total"])
        let remaining = intVal(args["remaining"])
        let step = args["step"].map { intVal($0) }
        let taskName = args["task_name"] as? String ?? ""
        let taskId = args["task_id"] as? String ?? ""
        let completed = boolVal(args["completed"])
        let state = args["state"] as? String ?? (completed ? "COMPLETED" : "RUNNING")
        let inProgress = stringList(args["in_progress"])
        let current = inProgress.first ?? ""
        let hasCounts = total > 0 || done > 0 || completed || !taskId.isEmpty
        guard hasCounts else { return nil }
        let detail = (fallbackDetail?.isEmpty == false)
            ? fallbackDetail!
            : [taskName, total > 0 ? "\(done)/\(total)" : nil, current.isEmpty ? nil : current]
                .compactMap { $0 }.joined(separator: " · ")
        return ToolProgress(
            taskId: taskId, taskName: taskName, done: done, total: total,
            remaining: remaining, currentItem: current, completed: completed,
            state: state, detail: detail, step: step
        )
    }

    private static func from(detail: String, name: String) -> ToolProgress? {
        // "notes · 190/292 · item_190" or legacy "worker 190/292"
        let ratio = try? NSRegularExpression(pattern: #"(\d+)\s*/\s*(\d+)"#)
        let range = NSRange(detail.startIndex..<detail.endIndex, in: detail)
        var done = 0
        var total = 0
        if let match = ratio?.firstMatch(in: detail, range: range),
           match.numberOfRanges >= 3,
           let doneR = Range(match.range(at: 1), in: detail),
           let totalR = Range(match.range(at: 2), in: detail) {
            done = Int(detail[doneR]) ?? 0
            total = Int(detail[totalR]) ?? 0
        }
        var step: Int? = nil
        if let stepMatch = detail.range(of: #"step\s+(\d+)"#, options: .regularExpression) {
            let digits = detail[stepMatch].filter(\.isNumber)
            step = Int(digits)
        }
        guard total > 0 || step != nil || name == "work_ledger" else { return nil }
        let parts = detail.split(separator: "·").map {
            $0.trimmingCharacters(in: .whitespaces)
        }
        var taskName = ""
        if let first = parts.first, !first.contains("/") && !first.hasPrefix("step")
            && first != "worker" && first != "running" {
            taskName = first
        }
        let current = parts.last(where: {
            !$0.contains("/") && !$0.hasPrefix("step") && $0 != taskName
                && $0 != "worker" && $0 != "running"
        }) ?? ""
        return ToolProgress(
            taskId: "", taskName: taskName, done: done, total: total,
            remaining: max(0, total - done), currentItem: current,
            completed: total > 0 && done >= total,
            state: (total > 0 && done >= total) ? "COMPLETED" : "RUNNING",
            detail: detail, step: step
        )
    }

    private static func intVal(_ any: Any?) -> Int {
        if let i = any as? Int { return i }
        if let n = any as? NSNumber { return n.intValue }
        if let d = any as? Double { return Int(d) }
        if let s = any as? String, let i = Int(s) { return i }
        return 0
    }

    private static func boolVal(_ any: Any?) -> Bool {
        if let b = any as? Bool { return b }
        if let n = any as? NSNumber { return n.boolValue }
        if let s = any as? String {
            return s.lowercased() == "true" || s == "1"
        }
        return false
    }

    private static func stringList(_ any: Any?) -> [String] {
        if let list = any as? [String] { return list }
        if let list = any as? [Any] {
            return list.compactMap { $0 as? String }.filter { !$0.isEmpty }
        }
        if let s = any as? String, !s.isEmpty { return [s] }
        return []
    }
}

// MARK: - Protocol v1 typed frames

/// The protocol version this shell speaks. Compared against the ``proto``
/// field in ``ready`` — a mismatch is surfaced, never silently degraded.
enum ProtocolV1 {
    static let version = "1"
}

/// Every agent→client frame, decoded strictly by its ``type`` discriminator.
/// THE typed mirror of ``jaeger_os/contract/protocol.py`` — shapes are
/// pinned by ProtocolFixtureTests against ``protocol_v1_fixtures.json``,
/// the same fixture file the Python side asserts its builders against.
/// An unknown ``type`` decodes to nil (forward-compatible: new frames from
/// a newer core are skipped, not fatal).
enum ProtocolFrame {
    case ready(BridgeReady)
    case agentState(AgentLifecycle)
    case state(busy: Bool)
    /// ``detail`` is a v1 ADDITIVE optional — short human context for the
    /// activity chip (today: which skill loaded, e.g. "view scheduling").
    /// ``progress`` is also additive — a work-ledger snapshot for the
    /// live task drawer / hotkey HUD. Nil on ordinary tool chips and
    /// on older cores that omit ``args``.
    case tool(name: String, phase: String, elapsed: Double, detail: String?,
              progress: ToolProgress?)
    /// ``telemetry`` fields are v1 ADDITIVE optionals — a core that
    /// doesn't send them (or an older fixture) decodes to nils.
    case reply(text: String, error: String?,
               elapsedS: Double?, ctxUsed: Int?, ctxMax: Int?)
    case result(id: String, ok: Bool, error: String?, data: Data?)
    case request(BridgeRequest)
    /// ``suggestedName`` is a v1 ADDITIVE optional (nil when the core
    /// omits it, or on an older core) — the operator's CLI-pinned agent
    /// name, sent alongside ``kind="no_instance"`` so onboarding can
    /// default the identity step to it.
    case fatal(error: String, kind: String, suggestedName: String?)
    case bye

    static func decode(_ frame: Data) -> ProtocolFrame? {
        guard let obj = (try? JSONSerialization.jsonObject(with: frame))
                as? [String: Any],
              let type = obj["type"] as? String
        else { return nil }
        switch type {
        case "ready":
            return .ready(BridgeReady(
                instance: obj["instance"] as? String ?? "",
                model: obj["model"] as? String,
                character: obj["character"] as? String,
                icon: obj["icon"] as? String,
                proto: obj["proto"] as? String ?? "0",
                capabilities: obj["capabilities"] as? [String] ?? [],
                agent: obj["agent"] as? String ?? "ready",
                agentName: obj["agent_name"] as? String))
        case "agent_state":
            switch obj["state"] as? String ?? "" {
            case "booting":
                return .agentState(.booting)
            case "ready":
                return .agentState(.ready(model: obj["model"] as? String,
                                          character: obj["character"] as? String,
                                          icon: obj["icon"] as? String,
                                          agentName: obj["agent_name"] as? String))
            case "failed":
                return .agentState(.failed(obj["error"] as? String ?? "agent failed"))
            default:
                return nil
            }
        case "state":
            return .state(busy: obj["busy"] as? Bool ?? false)
        case "tool":
            let name = obj["name"] as? String ?? ""
            let phase = obj["phase"] as? String ?? "start"
            let detail = obj["detail"] as? String
            let args = obj["args"] as? [String: Any]
            return .tool(name: name,
                         phase: phase,
                         elapsed: (obj["elapsed_s"] as? Double) ?? 0,
                         detail: detail,
                         progress: ToolProgress.parse(name: name,
                                                      detail: detail,
                                                      args: args))
        case "reply":
            return .reply(text: obj["text"] as? String ?? "",
                          error: obj["error"] as? String,
                          elapsedS: (obj["elapsed_s"] as? NSNumber)?.doubleValue,
                          ctxUsed: (obj["ctx_used"] as? NSNumber)?.intValue,
                          ctxMax: (obj["ctx_max"] as? NSNumber)?.intValue)
        case "result":
            var payload: Data? = nil
            if let d = obj["data"], !(d is NSNull) {
                payload = try? JSONSerialization.data(withJSONObject: d,
                                                      options: [.fragmentsAllowed])
            }
            return .result(id: obj["id"] as? String ?? "",
                           ok: obj["ok"] as? Bool ?? true,
                           error: obj["error"] as? String, data: payload)
        case "request":
            return .request(BridgeRequest(
                id: obj["id"] as? String ?? "",
                kind: obj["kind"] as? String ?? "approval",
                prompt: obj["prompt"] as? String ?? "",
                options: obj["options"] as? [String] ?? []))
        case "fatal":
            return .fatal(error: obj["error"] as? String ?? "bridge failed",
                          kind: obj["kind"] as? String ?? "boot",
                          suggestedName: obj["suggested_name"] as? String)
        case "bye":
            return .bye
        default:
            return nil
        }
    }
}
