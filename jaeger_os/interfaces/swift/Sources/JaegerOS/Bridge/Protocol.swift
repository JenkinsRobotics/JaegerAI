//
//  Protocol.swift
//  JaegerOS / Bridge
//
//  Swift mirror of jaeger_os/agent/protocol.py.  The agent speaks
//  newline-delimited JSON over a Unix socket; this file defines the
//  three message shapes and the JSON codec that go on the wire.
//
//  Wire format (terse, one frame per line):
//
//      Request   {"id": <int>, "op": <str>, "params": {...}?}
//      Response  ok=true:  {"id": <int>, "ok": true, "result": <any>}
//                ok=false: {"id": <int>, "ok": false, "error": <str>}
//      Event     {"event": <str>, <payload key>: <value>, ...}
//
//  ``params`` is optional on requests (omitted when there are none).
//  ``result`` is omitted on null/empty success responses.
//  Events flatten the payload alongside the ``event`` discriminator,
//  matching the Python encoder's ``{"event": name, **payload}`` shape.
//

import Foundation

// MARK: - Message shapes

/// A client → agent request. ``id`` is the correlation token the
/// matching :class:`Response` carries back.
struct Request: Encodable {
    let id: Int
    let op: String
    let params: [String: AnyEncodable]?

    init(id: Int, op: String, params: [String: AnyEncodable]? = nil) {
        self.id = id
        self.op = op
        self.params = params
    }

    enum CodingKeys: String, CodingKey { case id, op, params }
}

/// A agent → client reply. Either ``ok == true`` with a
/// (possibly absent) ``result`` payload, or ``ok == false`` with an
/// ``error`` string.  Built by ``NDJSON.decodeResponse`` from
/// ``JSONSerialization`` output — no Codable conformance needed (and
/// ``AnyDecodable`` isn't a Codable type anyway).
struct Response {
    let id: Int
    let ok: Bool
    let result: AnyDecodable?
    let error: String?
}

/// An unsolicited agent → client message — streaming token deltas,
/// tool-call progress, status changes, etc.  The ``payload`` dict
/// holds whichever event-specific fields the agent sent alongside
/// the ``event`` discriminator.
///
/// ``@unchecked Sendable`` is honest here: the wrapped values come
/// from ``JSONSerialization`` (NSDictionary / NSNumber / NSString —
/// all immutable and thread-safe) and the struct itself is a
/// straight ``let``-only data carrier.
struct Event: @unchecked Sendable {
    let name: String
    let payload: [String: AnyDecodable]
}

/// Discriminated union — every parsed frame is one of these three.
enum Message {
    case request(Request)
    case response(Response)
    case event(Event)
}


// MARK: - Codec

/// Newline-delimited JSON codec.  Mirrors
/// ``jaeger_os/agent/protocol.py``'s ``encode`` / ``decode`` /
/// ``Framer``.
enum NDJSON {

    /// Serialize a request as one UTF-8 frame, terminating newline
    /// included.  Compact separators + ``ensure_ascii=False``-style
    /// behavior to match the Python encoder byte-for-byte where it
    /// matters (it shouldn't, since the agent's decoder is JSON
    /// tolerant, but matching keeps wire-level diffs clean).
    static func encode(_ request: Request) throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.withoutEscapingSlashes]
        var data = try encoder.encode(request)
        data.append(0x0A)  // '\n'
        return data
    }

    /// Decode one frame (no terminator) into a Message. Discriminates
    /// by inspecting which keys are present — same heuristic the
    /// Python ``decode`` uses: ``op`` → Request, ``ok`` → Response,
    /// ``event`` → Event.
    static func decode(_ frame: Data) throws -> Message {
        let json = try JSONSerialization.jsonObject(with: frame, options: [])
        guard let obj = json as? [String: Any] else {
            throw DecodeError.notAnObject
        }
        if obj["op"] != nil { return .request(try decodeRequest(obj)) }
        if obj["ok"] != nil { return .response(try decodeResponse(obj)) }
        if obj["event"] != nil { return .event(try decodeEvent(obj)) }
        throw DecodeError.unknownMessageKind(obj.keys.sorted())
    }

    private static func decodeRequest(_ obj: [String: Any]) throws -> Request {
        guard let id = obj["id"] as? Int, let op = obj["op"] as? String else {
            throw DecodeError.missingField("id|op")
        }
        // Params handling: we don't typically decode incoming Requests
        // (we're the client) — but keep this complete for symmetry.
        return Request(id: id, op: op, params: nil)
    }

    private static func decodeResponse(_ obj: [String: Any]) throws -> Response {
        guard let id = obj["id"] as? Int, let ok = obj["ok"] as? Bool else {
            throw DecodeError.missingField("id|ok")
        }
        let result = obj["result"].map(AnyDecodable.init(_:))
        let error = obj["error"] as? String
        return Response(id: id, ok: ok, result: result, error: error)
    }

    private static func decodeEvent(_ obj: [String: Any]) throws -> Event {
        guard let name = obj["event"] as? String else {
            throw DecodeError.missingField("event")
        }
        var payload: [String: AnyDecodable] = [:]
        for (k, v) in obj where k != "event" {
            payload[k] = AnyDecodable(v)
        }
        return Event(name: name, payload: payload)
    }

    enum DecodeError: Error, CustomStringConvertible {
        case notAnObject
        case missingField(String)
        case unknownMessageKind([String])

        var description: String {
            switch self {
            case .notAnObject:
                return "expected a JSON object at the frame root"
            case .missingField(let f):
                return "missing required field(s): \(f)"
            case .unknownMessageKind(let keys):
                return "no discriminator (op|ok|event) in frame; keys=\(keys)"
            }
        }
    }
}


// MARK: - NDJSON frame stream

/// Stateful framer that splits an inbound byte stream on ``\n`` and
/// hands back complete JSON frames.  Mirrors the Python ``Framer``
/// — partial frames buffer until the next ``feed`` call completes
/// them.  Necessary because TCP / Unix-socket reads aren't aligned
/// to message boundaries.
final class FrameStream {
    private var buffer = Data()

    /// Append bytes from the wire; return any complete frames now
    /// parseable.  Each returned ``Data`` is one frame, no newline.
    func feed(_ chunk: Data) -> [Data] {
        buffer.append(chunk)
        var frames: [Data] = []
        while let nl = buffer.firstIndex(of: 0x0A) {
            let frame = buffer.subdata(in: buffer.startIndex..<nl)
            // Drop the newline we matched on.
            buffer.removeSubrange(buffer.startIndex...nl)
            // Skip empties (defensive — the agent's encoder never
            // emits a bare ``\n``, but stay lenient).
            if !frame.isEmpty { frames.append(frame) }
        }
        return frames
    }
}


// MARK: - Type-erased JSON values

/// Encode arbitrary ``Encodable`` values into the ``params`` dict on
/// outgoing requests.  Mirrors the ``Any``-typed kwargs the agent
/// accepts on the Python side.
///
/// ``@unchecked Sendable`` is honest because callers only ever
/// construct this from immutable value-typed payloads (String, Int,
/// Bool, dictionaries of same) — the captured ``encode`` closure
/// references that immutable value, never touches shared mutable
/// state.
struct AnyEncodable: Encodable, @unchecked Sendable {
    private let _encode: (Encoder) throws -> Void

    init<T: Encodable>(_ value: T) {
        self._encode = value.encode(to:)
    }

    func encode(to encoder: Encoder) throws { try _encode(encoder) }
}

/// Decode arbitrary JSON values from incoming Responses and Events
/// without forcing the caller to know the shape ahead of time.
/// Wraps the raw ``Any`` produced by ``JSONSerialization`` and
/// exposes a convenience accessor.
///
/// ``@unchecked Sendable`` is fine for the same reason as ``Event`` —
/// the wrapped value is always a JSONSerialization-produced immutable
/// Foundation type (NSDictionary / NSArray / NSNumber / NSString).
struct AnyDecodable: @unchecked Sendable {
    let value: Any

    init(_ value: Any) { self.value = value }

    /// Convenience: pull out a value if it's of the expected type.
    func get<T>(_ type: T.Type) -> T? { value as? T }
}
