//
//  SettingsStore.swift
//  JaegerOS / MenuCard
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
    let type: String            // bool | int | float | str | enum
    let choices: [String]?      // present for enum
    let defaultValue: SettingValue
    let current: SettingValue
    let description: String
    let restart: Bool
    let advanced: Bool
    let validation: Validation

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
        case current, description, restart, advanced, validation
    }

    func withCurrent(_ v: SettingValue) -> Setting {
        Setting(path: path, label: label, group: group, type: type,
                choices: choices, defaultValue: defaultValue, current: v,
                description: description, restart: restart, advanced: advanced,
                validation: validation)
    }
}

/// A rendered settings page — one per live group, in page order.
struct SettingGroup: Identifiable, Equatable {
    let name: String
    let settings: [Setting]
    var id: String { name }
}

// MARK: - store

@MainActor
final class SettingsStore: ObservableObject {
    static let shared = SettingsStore(agent: AgentBridge.shared)

    private let agent: AgentBridge
    private var isPreloading = false

    @Published var characters: [CharacterSummary] = []
    @Published var detail: CharacterDetail?
    @Published var permissions: PermissionsInfo?
    /// The schema-derived settings, grouped + page-ordered. Rendered
    /// generically by the App Settings page — no field is hardcoded.
    @Published var settingsGroups: [SettingGroup] = []
    /// A change this session asked for an agent restart to take effect.
    @Published var settingsRestartNeeded = false
    /// Last settings error, surfaced inline on the App page.
    @Published var settingsError: String?
    @Published var busy = false

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
        "model", "display", "voice", "tts", "autonomy",
        "permissions", "retention", "interaction", "general",
    ]

    init(agent: AgentBridge) { self.agent = agent }

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
    /// Fetch + decode the grouped catalog. Idempotent unless ``force``.
    func loadSettingsCatalog(force: Bool = false) async {
        if !settingsGroups.isEmpty && !force { return }
        let r = await agent.query("settings_catalog")
        guard r.ok, let json = r.json,
              let dict = try? JSONDecoder().decode([String: [Setting]].self,
                                                   from: json)
        else { return }
        settingsGroups = Self.order(dict)
    }

    private static func order(_ dict: [String: [Setting]]) -> [SettingGroup] {
        let present = Set(dict.keys)
        var names = groupOrder.filter { present.contains($0) }
        names += present.subtracting(groupOrder).sorted()
        return names.map { SettingGroup(name: $0, settings: dict[$0] ?? []) }
    }

    func loadPermissions() async {
        if permissions != nil { return }
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
    /// (``settings_set`` → ``core/settings/catalog.set_value``). Optimistic:
    /// the local model updates immediately; on a backend rejection the error
    /// surfaces on ``settingsError`` and the catalog is reloaded to snap the
    /// UI back to the true value. Returns true on success.
    @discardableResult
    func setSetting(_ path: String, _ value: SettingValue) async -> Bool {
        busy = true
        defer { busy = false }
        settingsError = nil
        let r = await agent.command("settings_set",
                                    args: ["path": path, "value": value.sendable])
        guard r.ok else {
            settingsError = r.error ?? "couldn't save \(path)"
            await loadSettingsCatalog(force: true)   // snap back to truth
            return false
        }
        if let json = r.json,
           let obj = (try? JSONSerialization.jsonObject(with: json)) as? [String: Any],
           obj["restart_required"] as? Bool == true {
            settingsRestartNeeded = true
        }
        applyLocal(path: path, value: value)
        return true
    }

    private func applyLocal(path: String, value: SettingValue) {
        settingsGroups = settingsGroups.map { g in
            SettingGroup(name: g.name, settings: g.settings.map { s in
                s.path == path ? s.withCurrent(value) : s
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
