//
//  SettingsStore.swift
//  JaegerAI / MenuCard
//
//  Consumes the bridge query/command API (jaeger_os/interfaces/bridge.py) — the
//  same character/config/permissions data the PySide6 HUD edits, reached over
//  the pipe. Decodes JSON into typed models; mutations forward to the tested
//  Python functions.
//

import Foundation

// MARK: - models (keys match the bridge JSON)

struct CharacterSummary: Codable, Identifiable {
    struct Stat: Codable { let key: String; let val: Double }
    let id: String
    let name: String
    let role: String
    let level: Int
    let revision: Double
    let icon: String?
    let card: String?
    let active: Bool
    let bound: Bool
    let stats: [Stat]
}

struct CharacterDetail: Codable {
    let id: String
    let name: String
    let role: String
    let level: Int
    let voice_tone: String
    let voice_id: String?
    let soul: String
    let backstory: String
    let custom_instructions: String
    let icon: String?
    let traits: [String: [String: Double]]
}

struct AppConfig: Codable {
    var name: String
    var role: String
    var default_mode: String
    var ui: String
    var voice_enabled: Bool
    var speak_replies: Bool
    var show_latency: Bool
    var show_tool_activity: Bool
    var idle_minutes: Int
    var allow_lazy_installs: Bool
    var permission_mode: String
}

struct PermissionsInfo: Codable {
    var mode: String
    var granted: [String]
}

/// ``version_check.cached_update_status`` shape (the ``check_update`` query) —
/// current/latest version, whether a newer release exists, and a link to its
/// notes. ``latest``/``notes_url`` are nil offline or when already current.
struct UpdateStatus: Codable, Equatable {
    var current: String
    var latest: String?
    var available: Bool
    var notes_url: String?
}

/// Outcome of the ``run_update`` command — the bridge shells out to
/// ``jaeger update`` (the SAME machinery the CLI runs) and reports back.
struct UpdateRunResult: Codable, Equatable {
    var restart_required: Bool
    var returncode: Int?
    var output: String
}

// MARK: - schema-derived settings catalog (the single source)

/// A heterogeneous setting value (the catalog's ``default`` / ``current``).
/// Decodes whatever JSON scalar the schema produced; re-serializes the same
/// shape when the change is sent back via ``settings_set``.
enum SettingValue: Codable, Equatable, Sendable {
    case bool(Bool)
    case int(Int)
    case double(Double)
    case string(String)
    case none

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .none; return }
        if let b = try? c.decode(Bool.self) { self = .bool(b); return }
        if let i = try? c.decode(Int.self) { self = .int(i); return }
        if let d = try? c.decode(Double.self) { self = .double(d); return }
        if let s = try? c.decode(String.self) { self = .string(s); return }
        self = .none
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .bool(let b): try c.encode(b)
        case .int(let i): try c.encode(i)
        case .double(let d): try c.encode(d)
        case .string(let s): try c.encode(s)
        case .none: try c.encodeNil()
        }
    }

    var asBool: Bool { if case .bool(let b) = self { return b }; return false }
    var asDouble: Double {
        switch self {
        case .int(let i): return Double(i)
        case .double(let d): return d
        case .string(let s): return Double(s) ?? 0
        case .bool(let b): return b ? 1 : 0
        case .none: return 0
        }
    }
    var asString: String {
        switch self {
        case .bool(let b): return b ? "true" : "false"
        case .int(let i): return String(i)
        case .double(let d): return String(d)
        case .string(let s): return s
        case .none: return ""
        }
    }
    /// JSON-serializable form for the ``settings_set`` args.
    var sendable: any Sendable {
        switch self {
        case .bool(let b): return b
        case .int(let i): return i
        case .double(let d): return d
        case .string(let s): return s
        case .none: return ""
        }
    }
}

/// One catalog descriptor — the schema field, rendered generically. NO field
/// is named in Swift; every property comes from the Python catalog.
struct Setting: Codable, Identifiable, Equatable {
    let path: String
    let label: String
    let group: String
    let type: String            // bool | int | float | str | enum | json | secret
    let choices: [String]?      // present for enum
    let defaultValue: SettingValue
    let current: SettingValue
    let description: String
    let restart: Bool
    let advanced: Bool
    let validation: Validation
    /// Secrets only: whether a value is stored. The catalog never sends the
    /// secret itself (``current`` is always ""), so this is the only status.
    let configured: Bool?

    var id: String { path }
    var isOverridden: Bool { current != defaultValue }

    struct Validation: Codable, Equatable {
        let min: Double?
        let max: Double?
        let pattern: String?
    }

    enum CodingKeys: String, CodingKey {
        case path, label, group, type, choices
        case defaultValue = "default"
        case current, description, restart, advanced, validation, configured
    }

    func withCurrent(_ v: SettingValue) -> Setting {
        Setting(path: path, label: label, group: group, type: type,
                choices: choices, defaultValue: defaultValue, current: v,
                description: description, restart: restart, advanced: advanced,
                validation: validation, configured: configured)
    }

    /// ``settings_set`` echoes the RAW stored value. For scalars that is the
    /// display value; json (a list/dict, not the catalog's string) and secrets
    /// (always "") need a catalog read-back instead.
    var acceptsSetReplyValue: Bool {
        ["bool", "int", "float", "str", "enum"].contains(type)
    }
}

/// A rendered settings page — one per live group, in page order.
struct SettingGroup: Identifiable, Equatable {
    let name: String
    let settings: [Setting]
    var id: String { name }
}

/// Where the catalog fetch stands. A failure keeps any previously loaded
/// groups on screen; the page flags them as possibly stale.
enum SettingsLoadState: Equatable {
    case idle
    case loading
    case loaded
    case failed(String)
}

/// Where one setting's most recent save stands. ``saved`` means the bridge
/// wrote the instance config and the row now shows the stored value — NOT
/// that a running process (bridge, Gateway) has applied it.
enum SettingSaveState: Equatable {
    case saving
    case saved(restartRequired: Bool)
    /// The write reported success but the stored value couldn't be read back,
    /// so the row still shows the value from before the save.
    case savedUnconfirmed(restartRequired: Bool)
    case failed(String)
}

/// The two bridge calls the settings catalog needs. ``AgentBridge`` is the
/// production conformer; tests substitute a scripted backend.
@MainActor
protocol SettingsBackend: AnyObject {
    func query(_ what: String, args: [String: any Sendable]) async -> QueryResult
    func settingsSet(path: String, value: SettingValue) async -> QueryResult
}

extension AgentBridge: SettingsBackend {
    func settingsSet(path: String, value: SettingValue) async -> QueryResult {
        await command("settings_set", args: ["path": path, "value": value.sendable])
    }
}

// MARK: - store

@MainActor
final class SettingsStore: ObservableObject {
    static let shared = SettingsStore(agent: AgentBridge.shared)

    private let agent: AgentBridge
    private let backend: SettingsBackend
    private var isPreloading = false

    @Published var characters: [CharacterSummary] = []
    @Published var detail: CharacterDetail?
    @Published var permissions: PermissionsInfo?
    /// The schema-derived settings, grouped + page-ordered. Rendered
    /// generically by the App Settings page — no field is hardcoded.
    @Published var settingsGroups: [SettingGroup] = []
    /// A change saved this session is marked as needing a restart to take effect.
    @Published var settingsRestartNeeded = false
    /// Catalog fetch state — failures surface on the App page with Retry.
    @Published private(set) var settingsLoad: SettingsLoadState = .idle
    /// Per-path outcome of the latest save, shown under that setting's row.
    @Published private(set) var settingSaves: [String: SettingSaveState] = [:]
    @Published var busy = false

    // Ordering for rapid edits. Every save gets a sequence number; only the
    // newest save for a path may publish its result. Writes run one at a time
    // (``writeTail``) so the bridge — which handles requests in pipe order —
    // persists them in the order they were made, and each read-back reflects
    // exactly its own write.
    private var writeSeq = 0
    private var latestWrite: [String: Int] = [:]
    private var pendingWrites: [String: Int] = [:]
    private var writeTail: Task<Void, Never>?
    private var catalogLoadSeq = 0

    /// Last-known ``check_update`` result — the Updates row and the
    /// menu-bar dot both read this, so a single background poll (app
    /// launch + every ~6h, see ``pollUpdatesIfDue``) lights up every
    /// surface at once.
    @Published var updateStatus: UpdateStatus?
    /// True while ``run_update`` (the actual upgrade subprocess) is running.
    @Published var updateInProgress = false
    /// Outcome of the last ``run_update`` — nil before one has run.
    @Published var updateResult: UpdateRunResult?
    /// Set when ``run_update`` couldn't even be dispatched (e.g. a turn
    /// was in flight) — distinct from a completed-but-failed run, which
    /// lands in ``updateResult`` instead.
    @Published var updateError: String?

    /// Page order mirrors ``catalog.GROUP_ORDER`` on the Python side.
    private static let groupOrder = [
        "model", "display", "interaction", "webui", "voice", "tts",
        "kokoro_tts", "whisper_stt", "persona", "skills", "autonomy",
        "warmup", "workspace", "webhooks", "containers", "permissions",
        "security", "avatar", "hardware", "retention", "general",
    ]

    init(agent: AgentBridge, backend: SettingsBackend? = nil) {
        self.agent = agent
        self.backend = backend ?? agent
    }

    func preload() async {
        guard !isPreloading else { return }
        isPreloading = true
        defer { isPreloading = false }
        await loadAll()
    }

    func loadAll() async {
        await loadInitial()
        await loadSettingsCatalog()
        await loadPermissions()
    }

    func loadInitial() async {
        await loadCharacters()
        await loadDetail()
    }

    func loadCharacters() async {
        if !characters.isEmpty { return }
        characters = await decode([CharacterSummary].self, "characters") ?? []
    }
    func loadDetail(id: String? = nil) async {
        if id == nil, detail != nil { return }
        let args: [String: any Sendable] = id.map { ["id": $0] } ?? [:]
        detail = await decode(CharacterDetail.self, "character", args: args)
    }
    /// Fetch + decode the grouped catalog. Idempotent unless ``force``. A
    /// failure lands on ``settingsLoad`` (never silent). The newest load wins,
    /// and a row saved while this load was in flight keeps its read-back
    /// value — the load may have read the file before that write.
    func loadSettingsCatalog(force: Bool = false) async {
        if !settingsGroups.isEmpty && !force { return }
        catalogLoadSeq += 1
        let seq = catalogLoadSeq
        let writesBefore = writeSeq
        settingsLoad = .loading
        let result = await fetchCatalog()
        guard seq == catalogLoadSeq else { return }
        switch result {
        case .success(let dict):
            settingsGroups = merge(Self.order(dict), keepingWritesAfter: writesBefore)
            settingsLoad = .loaded
        case .failure(let failure):
            settingsLoad = .failed(failure.message)
        }
    }

    private struct CatalogFailure: Error { let message: String }

    private func fetchCatalog(group: String? = nil) async
        -> Result<[String: [Setting]], CatalogFailure> {
        let args: [String: any Sendable] = group.map { ["group": $0] } ?? [:]
        let r = await backend.query("settings_catalog", args: args)
        guard r.ok else {
            return .failure(CatalogFailure(message: Self.loadFailureMessage(r.error)))
        }
        guard let json = r.json else {
            return .failure(CatalogFailure(message:
                "Couldn't load settings: the bridge answered with no data. Retry."))
        }
        do {
            return .success(try JSONDecoder().decode([String: [Setting]].self, from: json))
        } catch {
            return .failure(CatalogFailure(message:
                "Couldn't read the settings the bridge sent (\(Self.describe(error))). "
                + "The app and the Jaeger backend may be different versions."))
        }
    }

    /// Turn a bridge error into a message the operator can act on.
    static func loadFailureMessage(_ error: String?) -> String {
        let raw = (error ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let lower = raw.lowercased()
        if lower.contains("not connected") || lower.contains("not running")
            || lower.contains("bridge exited") {
            return "Couldn't load settings: the app isn't connected to its Jaeger "
                + "bridge. Check the status on Home, then Retry."
        }
        if lower.contains("timed out") {
            return "Couldn't load settings: the bridge didn't answer in time "
                + "(it may still be starting). Retry."
        }
        return "Couldn't load settings: \(raw.isEmpty ? "unknown bridge error" : raw)"
    }

    private static func describe(_ error: Error) -> String {
        switch error as? DecodingError {
        case .keyNotFound(let key, let ctx)?:
            return "missing \(Self.codingPath(ctx.codingPath + [key]))"
        case .typeMismatch(_, let ctx)?, .valueNotFound(_, let ctx)?:
            return "unexpected value at \(Self.codingPath(ctx.codingPath))"
        case .dataCorrupted?:
            return "malformed JSON"
        default:
            return error.localizedDescription
        }
    }

    private static func codingPath(_ keys: [CodingKey]) -> String {
        keys.map { $0.intValue.map { "[\($0)]" } ?? $0.stringValue }
            .joined(separator: ".")
    }

    /// A save issued after ``mark`` (or still queued) is newer than a load
    /// that started at ``mark``; that row keeps its local value.
    private func hasWrite(_ path: String, after mark: Int) -> Bool {
        (pendingWrites[path] ?? 0) > 0 || (latestWrite[path] ?? 0) > mark
    }

    private func merge(_ fresh: [SettingGroup],
                       keepingWritesAfter mark: Int) -> [SettingGroup] {
        let local = Dictionary(settingsGroups.flatMap(\.settings).map { ($0.path, $0) },
                               uniquingKeysWith: { first, _ in first })
        return fresh.map { g in
            SettingGroup(name: g.name, settings: g.settings.map { s in
                guard hasWrite(s.path, after: mark), let mine = local[s.path] else { return s }
                return mine
            })
        }
    }

    private static func order(_ dict: [String: [Setting]]) -> [SettingGroup] {
        let present = Set(dict.keys)
        var names = groupOrder.filter { present.contains($0) }
        names += present.subtracting(groupOrder).sorted()
        return names.map { SettingGroup(name: $0, settings: dict[$0] ?? []) }
    }

    func loadPermissions(force: Bool = false) async {
        if permissions != nil && !force { return }
        permissions = await decode(PermissionsInfo.self, "permissions")
    }

    private func decode<T: Decodable>(_ type: T.Type, _ what: String,
                                      args: [String: any Sendable] = [:]) async -> T? {
        let r = await agent.query(what, args: args)
        guard r.ok, let json = r.json else { return nil }
        return try? JSONDecoder().decode(T.self, from: json)
    }

    // mutations
    func select(_ id: String) async {
        if await run("select_character", ["id": id]) {
            characters = []
            detail = nil
            await loadCharacters()
            await loadDetail()
        }
    }
    func makeDefault(_ id: String) async {
        if await run("make_default", ["id": id]) {
            characters = []
            await loadCharacters()
        }
    }
    func saveProfile(role: String, voiceTone: String, voiceId: String,
                     soul: String, backstory: String, instructions: String) async {
        await run("save_profile", ["role": role, "voice_tone": voiceTone,
                                   "voice_id": voiceId, "soul": soul, "backstory": backstory,
                                   "custom_instructions": instructions])
    }
    func saveTraits(_ traits: [String: [String: Double]]) async {
        await run("save_traits", ["traits": traits])
    }
    /// Validate + persist ONE setting through the schema-derived catalog
    /// (``settings_set`` → ``core/settings/catalog.set_value``). The row's
    /// ``current`` changes only to what the backend stored — the catalog
    /// read-back, else the normalized value the save echoed — never the
    /// submitted value. The outcome lands on ``settingSaves[path]``.
    /// Returns true when THIS edit was written (even if a newer edit has since
    /// taken over the row); false when it failed or was superseded before it
    /// was sent.
    @discardableResult
    func setSetting(_ path: String, _ value: SettingValue) async -> Bool {
        writeSeq += 1
        let seq = writeSeq
        latestWrite[path] = seq
        pendingWrites[path, default: 0] += 1
        settingSaves[path] = .saving
        let previous = writeTail
        let write = Task { () -> Bool in
            await previous?.value
            return await self.performWrite(path, value, seq: seq)
        }
        writeTail = Task { _ = await write.value }
        return await write.value
    }

    private func performWrite(_ path: String, _ value: SettingValue, seq: Int) async -> Bool {
        defer {
            pendingWrites[path, default: 1] -= 1
            if pendingWrites[path] == 0 { pendingWrites[path] = nil }
        }
        // A newer edit to this path is already queued; send only that one.
        guard latestWrite[path] == seq else { return false }
        let before = setting(at: path)
        let r = await backend.settingsSet(path: path, value: value)
        let reply = r.json.flatMap { try? JSONDecoder().decode(SetReply.self, from: $0) }
        // Re-read even after an error: a failed reply doesn't prove the file
        // is unchanged (the write can land before the reply fails to encode).
        let stored = await readBack(path, group: before?.group)
        // A newer edit to this path was queued meanwhile; its result owns the
        // row. Publishing ours would flash an older value over the newer one.
        guard latestWrite[path] == seq else { return r.ok }

        guard r.ok else {
            let error = r.error ?? "Couldn't save \(path)."
            if let stored {
                replace(stored)
                if let before, stored.current != before.current
                    || stored.configured != before.configured {
                    settingSaves[path] = .failed(
                        "\(error) The stored value changed anyway — showing what's saved now.")
                    return false
                }
            }
            settingSaves[path] = .failed(error)
            return false
        }
        let restart = reply?.restart_required ?? before?.restart ?? false
        if restart { settingsRestartNeeded = true }
        if let stored {
            replace(stored)
            settingSaves[path] = .saved(restartRequired: restart)
        } else if let before, before.acceptsSetReplyValue, let echoed = reply?.value {
            replace(before.withCurrent(echoed))
            settingSaves[path] = .saved(restartRequired: restart)
        } else {
            settingSaves[path] = .savedUnconfirmed(restartRequired: restart)
        }
        return true
    }

    /// ``settings_set`` reply: ``{restart_required, path, value}``.
    private struct SetReply: Decodable {
        let restart_required: Bool?
        let value: SettingValue?
    }

    /// The authoritative descriptor for ``path`` straight from the catalog
    /// (narrowed to its group when known), or nil if it can't be read.
    private func readBack(_ path: String, group: String?) async -> Setting? {
        guard case .success(let dict) = await fetchCatalog(group: group) else { return nil }
        return dict.values.lazy.flatMap { $0 }.first { $0.path == path }
    }

    private func setting(at path: String) -> Setting? {
        settingsGroups.lazy.flatMap(\.settings).first { $0.path == path }
    }

    private func replace(_ stored: Setting) {
        settingsGroups = settingsGroups.map { g in
            SettingGroup(name: g.name, settings: g.settings.map { s in
                s.path == stored.path ? stored : s
            })
        }
    }
    func revoke(_ skill: String) async {
        if await run("revoke_permission", ["skill": skill]) {
            permissions = nil
            await loadPermissions()
        }
    }

    // MARK: - instance identity (agent name + profile picture)

    /// Rename the agent (identity.yaml ``name``). Refreshes the live status so
    /// the tray/header/HUD pick up the new name immediately.
    @discardableResult
    func saveAgentName(_ name: String) async -> Bool {
        let ok = await run("save_identity", ["name": name])
        if ok { await agent.refreshIdentity() }
        return ok
    }
    /// Set a custom profile picture from a file the operator picked (copied
    /// into the instance dir by the bridge). Empty path clears it → the
    /// effective avatar falls back to the active character's card.
    @discardableResult
    func setAvatar(path: String) async -> Bool {
        let ok = await run("save_identity", ["avatar": path])
        if ok { await agent.refreshIdentity() }
        return ok
    }
    @discardableResult
    func clearAvatar() async -> Bool { await setAvatar(path: "") }

    @discardableResult
    private func run(_ cmd: String, _ args: [String: any Sendable]) async -> Bool {
        busy = true
        defer { busy = false }
        return await agent.command(cmd, args: args).ok
    }

    // MARK: - in-app updates (0.8)

    /// Ask the bridge whether a newer release exists. Cheap to call often —
    /// the Python side caches the GitHub lookup for ~6h — so this is safe
    /// on app launch and on a periodic timer, not just the explicit button.
    @discardableResult
    func checkForUpdates() async -> UpdateStatus? {
        let r = await agent.query("check_update")
        guard r.ok, let json = r.json,
              let st = try? JSONDecoder().decode(UpdateStatus.self, from: json)
        else { return nil }
        updateStatus = st
        return st
    }

    /// Run the actual upgrade (shells out to ``jaeger update`` on the Python
    /// side — never reimplemented here). On success, ``updateResult.
    /// restart_required`` tells the caller to prompt a quit+reopen; this
    /// method never auto-restarts the app.
    func runUpdate() async {
        guard !updateInProgress else { return }
        updateInProgress = true
        updateError = nil
        defer { updateInProgress = false }
        let ref = updateStatus?.latest
        let args: [String: any Sendable] = ref.map { ["ref": $0] } ?? [:]
        let r = await agent.command("run_update", args: args)
        guard let json = r.json,
              let res = try? JSONDecoder().decode(UpdateRunResult.self, from: json)
        else {
            updateError = r.error ?? "update failed"
            return
        }
        updateResult = res
        if !r.ok { updateError = r.error }
    }
}
