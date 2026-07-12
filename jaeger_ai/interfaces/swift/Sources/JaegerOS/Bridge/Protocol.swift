//
//  Protocol.swift
//  JaegerOS / Bridge
//
//  Shared NDJSON value types + line framer for the stdio bridge. The bridge
//  speaks the JROS client protocol (see jaeger_os/protocol.py +
//  dev/docs/JROS_CLIENT_PROTOCOL.md); ``BridgeProcess`` parses the typed
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
    case tool(name: String, phase: String, elapsed: Double, detail: String?)
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
            return .tool(name: obj["name"] as? String ?? "",
                         phase: obj["phase"] as? String ?? "start",
                         elapsed: (obj["elapsed_s"] as? Double) ?? 0,
                         detail: obj["detail"] as? String)
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
