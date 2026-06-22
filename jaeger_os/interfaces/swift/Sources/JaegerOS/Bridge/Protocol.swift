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
