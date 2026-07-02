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

// MARK: - store

@MainActor
final class SettingsStore: ObservableObject {
    private let agent: AgentBridge

    @Published var characters: [CharacterSummary] = []
    @Published var detail: CharacterDetail?
    @Published var config: AppConfig?
    @Published var permissions: PermissionsInfo?
    @Published var busy = false

    init(agent: AgentBridge) { self.agent = agent }

    func loadAll() async {
        await loadCharacters()
        await loadDetail()
        await loadConfig()
        await loadPermissions()
    }

    func loadCharacters() async {
        characters = await decode([CharacterSummary].self, "characters") ?? []
    }
    func loadDetail(id: String? = nil) async {
        let args: [String: any Sendable] = id.map { ["id": $0] } ?? [:]
        detail = await decode(CharacterDetail.self, "character", args: args)
    }
    func loadConfig() async { config = await decode(AppConfig.self, "config") }
    func loadPermissions() async { permissions = await decode(PermissionsInfo.self, "permissions") }

    private func decode<T: Decodable>(_ type: T.Type, _ what: String,
                                      args: [String: any Sendable] = [:]) async -> T? {
        let r = await agent.query(what, args: args)
        guard r.ok, let json = r.json else { return nil }
        return try? JSONDecoder().decode(T.self, from: json)
    }

    // mutations
    func select(_ id: String) async {
        if await run("select_character", ["id": id]) { await loadCharacters(); await loadDetail() }
    }
    func makeDefault(_ id: String) async {
        if await run("make_default", ["id": id]) { await loadCharacters() }
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
    func saveConfig(_ c: AppConfig) async {
        await run("save_config", ["default_mode": c.default_mode, "ui": c.ui,
                                  "voice_enabled": c.voice_enabled, "speak_replies": c.speak_replies,
                                  "show_latency": c.show_latency,
                                  "show_tool_activity": c.show_tool_activity,
                                  "idle_minutes": c.idle_minutes,
                                  "allow_lazy_installs": c.allow_lazy_installs,
                                  "permission_mode": c.permission_mode])
    }
    func revoke(_ skill: String) async {
        if await run("revoke_permission", ["skill": skill]) { await loadPermissions() }
    }

    @discardableResult
    private func run(_ cmd: String, _ args: [String: any Sendable]) async -> Bool {
        busy = true
        defer { busy = false }
        return await agent.command(cmd, args: args).ok
    }
}
