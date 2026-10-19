import Foundation
import WebKit

struct PanelContext: Decodable { let profile: String; let auth_enabled: Bool; let csrf_token: String? }
struct CronCatalog: Decodable {
    let jobs: [CronRow]; let cron_unavailable: Bool?; let other_profile_count: Int?
}
struct CronRunning: Decodable { let running: [String: Double] }
struct CronHistory: Decodable {
    struct Run: Decodable, Identifiable {
        let filename: String; let modified: Double; var id: String { filename }
    }
    let runs: [Run]; let total: Int
}
struct CronRow: Decodable, Identifiable {
    let id: String; let name: String?; let schedule_display: String?
    let enabled: Bool?; let state: String?; let last_status: String?
    let prompt: String?; let deliver: String?
}
struct BoardCatalog: Decodable {
    struct Board: Decodable, Identifiable {
        let slug: String; let name: String?; var id: String { slug }
    }
    let boards: [Board]; let current: String
}
struct BoardSnapshot: Decodable {
    struct Column: Decodable, Identifiable {
        let name: String; let tasks: [Card]; var id: String { name }
    }
    struct Card: Decodable, Identifiable {
        let id: String; let title: String; let status: String
        let description: String?; let assignee: String?
    }
    let columns: [Column]; let read_only: Bool?
}

/// Reuses WebKit authentication. Never transfers Gateway credentials or follows redirects.
@MainActor
final class NativePanelClient {
    private var base: URL?
    private var cookies: [HTTPCookie] = []
    private(set) var context: PanelContext?
    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.httpShouldSetCookies = false; config.httpCookieStorage = nil
        config.timeoutIntervalForRequest = 15
        return URLSession(configuration: config, delegate: NativePanelRedirectGuard(), delegateQueue: nil)
    }()
    func connect() async throws {
        context = nil
        base = try await WebUIEndpoint.resolve(instance: AgentBridge.shared.status?.instance ?? AgentBridge.explicitInstance)
        cookies = await WKWebsiteDataStore.default().httpCookieStore.allCookies()
        context = try await get("/api/native/context")
    }
    func get<T: Decodable>(_ path: String, query: [URLQueryItem] = []) async throws -> T {
        try await perform(path, query:query, method:"GET", body:nil)
    }
    struct MutationReceipt: Decodable { let ok: Bool?; let job: CronRow?; let job_id: String? }
    func mutateSchedule(_ action: String, body: [String: Any]) async throws -> MutationReceipt {
        guard ["create", "update", "pause", "resume", "delete"].contains(action) else { throw failure("Unsupported scheduler action") }
        return try await perform("/api/crons/" + action, query:[], method:"POST", body:body)
    }
    private func perform<T: Decodable>(_ path: String, query: [URLQueryItem], method: String, body: [String: Any]?) async throws -> T {
        guard let base else { throw failure("WebUI disconnected. Refresh to connect.") }
        var parts = URLComponents(url: base, resolvingAgainstBaseURL: false)!
        parts.path = path; parts.queryItems = query.isEmpty ? nil : query; parts.fragment = nil
        guard let url = parts.url else { throw failure("Invalid WebUI address.") }
        var request = URLRequest(url: url)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpMethod = method
        if let body {
            guard let context else { throw failure("Refresh before changing a schedule.") }
            if context.auth_enabled && (context.csrf_token?.isEmpty ?? true) { throw failure("Sign in and refresh before changing a schedule.") }
            request.httpBody = try JSONSerialization.data(withJSONObject:body)
            request.setValue("application/json", forHTTPHeaderField:"Content-Type")
            if let token = context.csrf_token { request.setValue(token, forHTTPHeaderField:"X-Hermes-CSRF-Token") }
            var origin = URLComponents(url:base,resolvingAgainstBaseURL:false)!
            origin.path = ""; origin.query = nil; origin.fragment = nil
            request.setValue(origin.string, forHTTPHeaderField:"Origin")
        }
        let matching = Self.matchingCookies(cookies, for: url)
        for (key, value) in HTTPCookie.requestHeaderFields(with: matching) { request.setValue(value, forHTTPHeaderField: key) }
        if let context { request.setValue(context.profile, forHTTPHeaderField: "X-Jaeger-Expected-Profile") }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw failure("No WebUI response.") }
        switch http.statusCode {
        case 200...299: break
        case 301...399, 401: throw failure("Sign in through embedded WebUI chat, then refresh.")
        case 403: throw failure("WebUI permission denied. Sign in and refresh.")
        case 404: throw failure("This WebUI version does not support this panel endpoint.")
        case 503: throw failure("The connected WebUI service is unavailable or does not have this backend installed.")
        case 409: throw failure("WebUI profile changed. Refresh before continuing.")
        default: throw failure("WebUI request failed (HTTP \(http.statusCode)). Refresh to retry.")
        }
        guard http.value(forHTTPHeaderField: "Content-Type")?.contains("application/json") == true else {
            throw failure("WebUI returned a sign-in page or unsupported response. Sign in through embedded chat, then refresh.")
        }
        do { return try JSONDecoder().decode(T.self, from: data) }
        catch { throw failure("The WebUI response schema is unsupported by this app.") }
    }
    nonisolated static func matchingCookies(_ cookies: [HTTPCookie], for url: URL) -> [HTTPCookie] {
        cookies.filter { cookie in
            let domain = cookie.domain.hasPrefix(".") ? String(cookie.domain.dropFirst()) : cookie.domain
            let host = url.host ?? ""
            return (host == domain || (cookie.domain.hasPrefix(".") && host.hasSuffix("." + domain))) &&
                (!cookie.isSecure || url.scheme == "https") &&
                (url.path == cookie.path || url.path.hasPrefix(cookie.path.hasSuffix("/") ? cookie.path : cookie.path + "/")) &&
                (cookie.expiresDate.map { $0 > Date() } ?? true)
        }
    }

    private func failure(_ message: String) -> NSError {
        NSError(domain: "JaegerNativePanels", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}

private final class NativePanelRedirectGuard: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}
