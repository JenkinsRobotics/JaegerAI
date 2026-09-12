//
//  GatewaySessions.swift
//  JaegerAI / Bridge
//
//  Session + live-event half of the Gateway client. `GatewayClient` already
//  covers agents, health and handoffs; it had no way to create a session,
//  send a turn, or read the event stream — so the menu-bar app could list
//  agents and never hold a conversation through the persistence spine.
//
//  Routes mirror `core/gateway/server.py` exactly (read from its router
//  registrations, not assumed). Note `health` is `/health`, NOT `/v1/health`
//  — the latter 404s.
//
//      GET    /v1/sessions[?profile=]
//      POST   /v1/sessions
//      GET    /v1/sessions/{id}
//      DELETE /v1/sessions/{id}
//      POST   /v1/sessions/{id}/turns
//      POST   /v1/sessions/{id}/cancel
//      POST   /v1/sessions/{id}/reconcile
//      GET    /v1/sessions/{id}/stream          (SSE)
//      POST   /v1/approvals/{id}
//

import Foundation

extension GatewayClient {

    // MARK: - Wire types

    struct Session: Decodable, Identifiable, Sendable {
        let session_id: String
        let title: String?
        let profile: String?
        let workspace: String?
        let status: String?
        let agent_id: String?

        var id: String { session_id }
        var displayTitle: String { title ?? "Untitled" }
    }

    struct SessionList: Decodable, Sendable {
        let sessions: [Session]
    }

    /// The gateway's reply to `POST /v1/sessions/{id}/turns`.
    struct TurnAccepted: Decodable, Sendable {
        let session_id: String
        let turn_id: String
        let request_id: String
        let status: String
        let replayed: Bool?
    }

    /// One decoded SSE frame. `event` is the gateway's own event name —
    /// `turn.delta`, `turn.finish`, `approval.request`, and so on.
    struct StreamEvent: Sendable {
        let eventID: Int
        let sessionID: String
        let event: String
        /// Raw JSON of the `data` member, left undecoded on purpose: each
        /// event type has its own shape and callers decode what they need.
        let data: Data
        let timestamp: Double?

        /// Convenience for the token stream — `turn.delta` carries text.
        var deltaText: String? {
            guard event == "turn.delta",
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            else { return nil }
            return object["text"] as? String ?? object["delta"] as? String
        }

        var isTerminal: Bool {
            ["turn.finish", "turn.failed", "turn.cancelled"].contains(event)
        }
    }

    // MARK: - Session CRUD

    func listSessions(profile: String? = nil) async throws -> [Session] {
        var path = "v1/sessions"
        if let profile, !profile.isEmpty { path += "?profile=\(profile)" }
        let data = try await request(path: path)
        return try JSONDecoder().decode(SessionList.self, from: data).sessions
    }

    func createSession(title: String, profile: String = "jaeger") async throws -> Session {
        let data = try await request(
            path: "v1/sessions", method: "POST",
            jsonBody: ["title": title, "profile": profile]
        )
        return try JSONDecoder().decode(Session.self, from: data)
    }

    func getSession(id: String) async throws -> Session {
        let data = try await request(path: "v1/sessions/\(id)")
        return try JSONDecoder().decode(Session.self, from: data)
    }

    func deleteSession(id: String) async throws {
        _ = try await request(path: "v1/sessions/\(id)", method: "DELETE")
    }

    // MARK: - Turns

    /// Send a turn. Throws on 409 — the gateway's way of saying a turn is
    /// already in flight for this session, which the UI must surface rather
    /// than retry blindly.
    @discardableResult
    func sendTurn(sessionID: String, text: String, requestID: String? = nil) async throws -> TurnAccepted {
        var payload: [String: Any] = ["text": text]
        if let requestID { payload["request_id"] = requestID }
        let data = try await request(
            path: "v1/sessions/\(sessionID)/turns", method: "POST", jsonBody: payload
        )
        return try JSONDecoder().decode(TurnAccepted.self, from: data)
    }

    @discardableResult
    func cancelTurn(sessionID: String) async throws -> Bool {
        _ = try await request(path: "v1/sessions/\(sessionID)/cancel", method: "POST")
        return true
    }

    @discardableResult
    func resolveApproval(id: String, decision: String) async throws -> Bool {
        _ = try await request(
            path: "v1/approvals/\(id)", method: "POST",
            jsonBody: ["decision": decision, "approved": decision != "deny"]
        )
        return true
    }

    // MARK: - SSE stream

    /// Live events for one session, as an async sequence.
    ///
    /// Uses `URLSession.bytes` so frames arrive as the gateway writes them
    /// — a buffered request would deliver a completed turn all at once and
    /// defeat token-by-token speech.
    ///
    /// `lastEventID` resumes after a drop. The gateway replies **410** when
    /// the cursor has aged out of its replay window; that surfaces as a
    /// thrown `Failure` so the caller restarts from 0 rather than retrying a
    /// cursor that will never succeed.
    func streamEvents(
        sessionID: String,
        lastEventID: Int = 0
    ) -> AsyncThrowingStream<StreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                var path = "v1/sessions/\(sessionID)/stream"
                if lastEventID > 0 { path += "?last_event_id=\(lastEventID)" }
                guard let url = URL(string: path, relativeTo: baseURL) else {
                    continuation.finish(throwing: Failure(message: "Invalid stream URL"))
                    return
                }

                var urlRequest = URLRequest(url: url)
                urlRequest.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                urlRequest.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
                urlRequest.timeoutInterval = .infinity   // long-lived by design

                do {
                    let (bytes, response) = try await URLSession.shared.bytes(for: urlRequest)
                    if let http = response as? HTTPURLResponse, http.statusCode != 200 {
                        continuation.finish(throwing: Failure(
                            message: http.statusCode == 410
                                ? "Resume cursor expired — restart the stream from 0"
                                : "Gateway stream failed with HTTP \(http.statusCode)"
                        ))
                        return
                    }

                    // Minimal SSE framing: accumulate `event:`/`data:` until
                    // the blank line that terminates a frame.
                    var eventName = "message"
                    var dataLines: [String] = []

                    for try await line in bytes.lines {
                        if line.isEmpty {
                            if !dataLines.isEmpty,
                               let payload = dataLines.joined(separator: "\n").data(using: .utf8),
                               let event = Self.decodeFrame(payload, fallbackName: eventName) {
                                continuation.yield(event)
                            }
                            eventName = "message"
                            dataLines.removeAll()
                            continue
                        }
                        if line.hasPrefix("event:") {
                            eventName = String(line.dropFirst(6)).trimmingCharacters(in: .whitespaces)
                        } else if line.hasPrefix("data:") {
                            dataLines.append(String(line.dropFirst(5)).trimmingCharacters(in: .whitespaces))
                        }
                        // `id:` is carried inside the JSON payload too, so it
                        // is read from there rather than tracked separately.
                    }
                    continuation.finish()
                } catch {
                    // Never swallow: a dropped stream must reach the caller
                    // so the UI can show "reconnecting" instead of going quiet.
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    private static func decodeFrame(_ payload: Data, fallbackName: String) -> StreamEvent? {
        guard let object = try? JSONSerialization.jsonObject(with: payload) as? [String: Any]
        else { return nil }
        let inner = object["data"] ?? [:]
        let innerData = (try? JSONSerialization.data(withJSONObject: inner)) ?? Data()
        return StreamEvent(
            eventID: object["event_id"] as? Int ?? 0,
            sessionID: object["session_id"] as? String ?? "",
            event: object["event"] as? String ?? fallbackName,
            data: innerData,
            timestamp: object["timestamp"] as? Double
        )
    }
}
