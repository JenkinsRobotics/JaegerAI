//
//  AgentSettingsHUD.swift
//  JaegerOS / MenuCard
//
//  Agent-centric settings HUD — the Swift twin of the PySide6 ``agent_settings``
//  window. Left icon rail (Home · Library · Character · Traits · App ·
//  Permissions), an agent panel with the orb, and a content area per tab. All
//  tabs read/write real data via ``SettingsStore`` (the bridge query/command
//  API → the same tested Python functions the PySide6 HUD calls).
//

import AppKit
import SwiftUI

// MARK: - palette

enum HUD {
    static let bg     = Color(red: 0.047, green: 0.063, blue: 0.055)
    static let panel  = Color(red: 0.078, green: 0.102, blue: 0.090)
    static let field  = Color(red: 0.055, green: 0.082, blue: 0.071)
    static let stroke = Color(red: 0.137, green: 0.188, blue: 0.161)
    static let ink    = Color(red: 0.910, green: 0.937, blue: 0.918)
    static let inkDim = Color(red: 0.486, green: 0.541, blue: 0.506)
    static let accent = Color(red: 0.263, green: 0.878, blue: 0.541)

    static func section(_ t: String) -> some View {
        Text(t.uppercased())
            .font(.system(size: 11, weight: .bold)).tracking(2).foregroundStyle(inkDim)
    }
}

private enum Tab: String, CaseIterable, Identifiable {
    case home = "Home", library = "Library", character = "Character"
    case traits = "Traits", app = "App Settings", permissions = "Permissions"
    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .home: return "house"
        case .library: return "square.grid.2x2"
        case .character: return "person.crop.circle"
        case .traits: return "chart.bar"
        case .app: return "slider.horizontal.3"
        case .permissions: return "shield"
        }
    }
}

// MARK: - shell

struct AgentSettingsHUD: View {
    @ObservedObject private var agent = AgentBridge.shared
    @StateObject private var store = SettingsStore(agent: AgentBridge.shared)
    @State private var tab: Tab = .home

    private var name: String {
        store.detail?.name ?? agent.status?.character
            ?? agent.status?.instance ?? AgentBridge.defaultInstanceName
    }

    var body: some View {
        HStack(spacing: 0) {
            rail
            ScrollView {
                VStack(alignment: .leading, spacing: 14) { page }
                    .padding(EdgeInsets(top: 30, leading: 36, bottom: 26, trailing: 26))
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            agentPanel
        }
        .background(HUD.bg)
        .task { await store.loadAll() }
    }

    @ViewBuilder private var page: some View {
        switch tab {
        case .home: HomePage(store: store, name: name)
        case .library: LibraryPage(store: store)
        case .character: CharacterPage(store: store)
        case .traits: TraitsPage(store: store)
        case .app: AppPage(store: store)
        case .permissions: PermissionsPage(store: store)
        }
    }

    private var rail: some View {
        VStack(spacing: 6) {
            ForEach(Tab.allCases) { t in
                Button { tab = t } label: {
                    Image(systemName: t.symbol).font(.system(size: 18))
                        .foregroundStyle(tab == t ? HUD.accent : HUD.inkDim)
                        .frame(width: 44, height: 44)
                        .background(RoundedRectangle(cornerRadius: 12)
                            .fill(tab == t ? HUD.accent.opacity(0.16) : .clear))
                }.buttonStyle(.plain).help(t.rawValue)
            }
            Spacer()
            Button { studioComingSoon() } label: {
                Image(systemName: "link").font(.system(size: 20)).foregroundStyle(HUD.accent)
                    .frame(width: 44, height: 44)
                    .background(RoundedRectangle(cornerRadius: 14).fill(HUD.accent.opacity(0.12)))
            }.buttonStyle(.plain).help("Connect to Jaeger Studio")
        }
        .padding(.vertical, 16).padding(.horizontal, 9)
        .frame(width: 66).background(HUD.panel)
    }

    private var agentPanel: some View {
        VStack(spacing: 12) {
            Text(name.uppercased())
                .font(.system(size: 16, weight: .bold)).foregroundStyle(HUD.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
            VoiceOrbView(agent: agent)
            Spacer()
        }
        .padding(20).frame(width: 300).background(HUD.panel)
    }

    private func studioComingSoon() {
        let a = NSAlert()
        a.messageText = "Jaeger Studio"
        a.informativeText = "Jaeger Studio integration is coming soon."
        a.runModal()
    }
}

// MARK: - shared bits

private func statBar(_ frac: Double) -> some View {
    let n = 14, filled = Int((max(0, min(1, frac)) * Double(n)).rounded())
    return HStack(spacing: 3) {
        ForEach(0..<n, id: \.self) { i in
            RoundedRectangle(cornerRadius: 2).fill(i < filled ? HUD.accent : HUD.stroke)
        }
    }.frame(height: 10)
}

private func traitRow(_ name: String, _ frac: Double) -> some View {
    HStack(spacing: 12) {
        Text(name.replacingOccurrences(of: "_", with: " ").uppercased())
            .font(.system(size: 12, weight: .semibold)).foregroundStyle(HUD.ink)
            .frame(width: 150, alignment: .leading)
        statBar(frac)
        Text("\(Int((frac * 100).rounded()))")
            .font(.system(size: 11, weight: .bold)).foregroundStyle(HUD.accent)
            .frame(width: 34, alignment: .trailing)
    }
}

private func hudField(_ label: String, _ text: Binding<String>, multiline: Bool = false) -> some View {
    VStack(alignment: .leading, spacing: 4) {
        Text(label.uppercased()).font(.system(size: 10, weight: .semibold))
            .tracking(1).foregroundStyle(HUD.inkDim)
        Group {
            if multiline {
                TextEditor(text: text).frame(minHeight: 70).scrollContentBackground(.hidden)
            } else {
                TextField("", text: text).textFieldStyle(.plain)
            }
        }
        .font(.system(size: 13)).foregroundStyle(HUD.ink).padding(8)
        .background(RoundedRectangle(cornerRadius: 8).fill(HUD.field))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(HUD.stroke, lineWidth: 1))
    }
}

private func saveButton(_ title: String, _ action: @escaping () -> Void) -> some View {
    Button(action: action) {
        Text(title).font(.system(size: 13, weight: .bold)).foregroundColor(Color(red: 0.02, green: 0.08, blue: 0.05))
            .padding(.horizontal, 18).padding(.vertical, 8)
            .background(RoundedRectangle(cornerRadius: 9).fill(HUD.accent))
    }.buttonStyle(.plain)
}

// MARK: - pages

private struct HomePage: View {
    @ObservedObject var store: SettingsStore
    let name: String
    var body: some View {
        Text(name.uppercased()).font(.system(size: 34, weight: .heavy)).foregroundStyle(HUD.ink)
        Text("LVL \(store.detail?.level ?? 1)  ·  agent overview")
            .font(.system(size: 12)).foregroundStyle(HUD.inkDim)
        Spacer().frame(height: 12)
        HUD.section("Characteristics")
        let active = store.characters.first(where: { $0.active })
        ForEach(Array((active?.stats ?? []).sorted { abs($0.val - 0.5) > abs($1.val - 0.5) }.prefix(10)), id: \.key) { s in
            traitRow(s.key, s.val)
        }
    }
}

private struct LibraryPage: View {
    @ObservedObject var store: SettingsStore
    private let cols = [GridItem(.adaptive(minimum: 250), spacing: 16)]
    var body: some View {
        HStack { HUD.section("Character Library"); Text("· \(store.characters.count)").foregroundStyle(HUD.inkDim); Spacer() }
        LazyVGrid(columns: cols, spacing: 16) {
            ForEach(store.characters) { c in card(c) }
        }
    }
    private func card(_ c: CharacterSummary) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("rev \(String(format: "%.1f", c.revision))").font(.system(size: 10)).foregroundStyle(HUD.inkDim)
                Spacer()
                Text("Lv \(c.level)").font(.system(size: 11, weight: .bold)).foregroundColor(.black)
                    .padding(.horizontal, 8).padding(.vertical, 2)
                    .background(Capsule().fill(HUD.accent))
            }
            Text(c.name.uppercased()).font(.system(size: 17, weight: .heavy)).foregroundStyle(HUD.ink)
            Text(c.role).font(.system(size: 11)).foregroundStyle(HUD.inkDim).lineLimit(1)
            HStack(spacing: 14) {
                ForEach(Array(c.stats.sorted { abs($0.val - 0.5) > abs($1.val - 0.5) }.prefix(3)), id: \.key) { s in
                    VStack(spacing: 0) {
                        Text(String(s.key.prefix(4)).uppercased()).font(.system(size: 9, weight: .bold)).foregroundStyle(HUD.inkDim)
                        Text("\(Int(s.val * 100))").font(.system(size: 14, weight: .bold)).foregroundStyle(HUD.ink)
                    }
                }
            }
            HStack(spacing: 8) {
                Button { Task { await store.select(c.id) } } label: {
                    Text(c.active ? "✓ SELECTED" : "SELECT").font(.system(size: 12, weight: .bold))
                        .foregroundColor(.black).frame(maxWidth: .infinity).padding(.vertical, 8)
                        .background(RoundedRectangle(cornerRadius: 8).fill(c.active ? Color.green.opacity(0.8) : HUD.accent))
                }.buttonStyle(.plain)
                Button { Task { await store.makeDefault(c.id) } } label: {
                    Text(c.bound ? "★ DEFAULT" : "MAKE DEFAULT").font(.system(size: 12, weight: .bold))
                        .foregroundStyle(c.bound ? HUD.accent : HUD.ink).frame(maxWidth: .infinity).padding(.vertical, 8)
                        .background(RoundedRectangle(cornerRadius: 8).stroke(c.bound ? HUD.accent : HUD.stroke, lineWidth: 1))
                }.buttonStyle(.plain).disabled(c.bound)
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 12).fill(c.active ? HUD.accent.opacity(0.10) : HUD.field))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(c.active ? HUD.accent : HUD.stroke, lineWidth: 1))
    }
}

private struct CharacterPage: View {
    @ObservedObject var store: SettingsStore
    @State private var role = ""
    @State private var tone = ""
    @State private var voice = ""
    @State private var soul = ""
    @State private var back = ""
    @State private var instr = ""
    @State private var loadedId: String?
    var body: some View {
        HUD.section("Character")
        hudField("Role", $role)
        HStack { hudField("Voice tone", $tone); hudField("Voice ID", $voice) }
        hudField("Soul (core narrative)", $soul, multiline: true)
        hudField("Backstory", $back, multiline: true)
        hudField("Custom instructions", $instr, multiline: true)
        saveButton("Save character") {
            Task { await store.saveProfile(role: role, voiceTone: tone, voiceId: voice,
                                           soul: soul, backstory: back, instructions: instr) }
        }
        Color.clear.frame(height: 1).onAppear { sync() }
            .onChange(of: store.detail?.id) { _, _ in loadedId = nil; sync() }
    }
    private func sync() {
        guard let d = store.detail, loadedId != d.id else { return }
        role = d.role; tone = d.voice_tone; voice = d.voice_id ?? ""
        soul = d.soul; back = d.backstory; instr = d.custom_instructions; loadedId = d.id
    }
}

private struct TraitsPage: View {
    @ObservedObject var store: SettingsStore
    @State private var traits: [String: [String: Double]] = [:]
    @State private var loadedId: String?
    private let layers = ["hexaco", "special", "expression", "domains"]
    var body: some View {
        HUD.section("Traits")
        ForEach(layers, id: \.self) { layer in
            if let keys = traits[layer].map({ Array($0.keys).sorted() }), !keys.isEmpty {
                Text(layer.uppercased()).font(.system(size: 10, weight: .bold)).tracking(2).foregroundStyle(HUD.accent)
                ForEach(keys, id: \.self) { key in
                    HStack(spacing: 12) {
                        Text(key.replacingOccurrences(of: "_", with: " ").uppercased())
                            .font(.system(size: 12)).foregroundStyle(HUD.ink).frame(width: 150, alignment: .leading)
                        Slider(value: Binding(
                            get: { traits[layer]?[key] ?? 0 },
                            set: { traits[layer, default: [:]][key] = $0 }), in: 0...1).tint(HUD.accent)
                        Text("\(Int(((traits[layer]?[key] ?? 0)) * 100))")
                            .font(.system(size: 11, weight: .bold)).foregroundStyle(HUD.accent).frame(width: 34)
                    }
                }
            }
        }
        saveButton("Save traits") { Task { await store.saveTraits(traits) } }
        Color.clear.frame(height: 1).onAppear { sync() }
            .onChange(of: store.detail?.id) { _, _ in loadedId = nil; sync() }
    }
    private func sync() {
        guard let d = store.detail, loadedId != d.id else { return }
        traits = d.traits; loadedId = d.id
    }
}

private struct AppPage: View {
    @ObservedObject var store: SettingsStore
    @State private var c: AppConfig?
    var body: some View {
        HUD.section("App Settings")
        if let cfg = Binding($c) {
            Picker("Default interface", selection: cfg.default_mode) {
                ForEach(["tui", "gui", "voice"], id: \.self) { Text($0) }
            }.foregroundStyle(HUD.ink)
            Picker("Windowed UI toolkit", selection: cfg.ui) {
                ForEach(["swift", "pyside6"], id: \.self) { Text($0) }
            }.foregroundStyle(HUD.ink)
            Toggle("Voice input (mic) at boot", isOn: cfg.voice_enabled).tint(HUD.accent).foregroundStyle(HUD.ink)
            Toggle("Speak replies (speaker)", isOn: cfg.speak_replies).tint(HUD.accent).foregroundStyle(HUD.ink)
            Toggle("Show latency", isOn: cfg.show_latency).tint(HUD.accent).foregroundStyle(HUD.ink)
            Toggle("Show tool activity", isOn: cfg.show_tool_activity).tint(HUD.accent).foregroundStyle(HUD.ink)
            Toggle("Allow lazy installs", isOn: cfg.allow_lazy_installs).tint(HUD.accent).foregroundStyle(HUD.ink)
            saveButton("Save settings") { if let v = c { Task { await store.saveConfig(v) } } }
        } else {
            Text("Loading…").foregroundStyle(HUD.inkDim)
        }
        Color.clear.frame(height: 1).onAppear { if c == nil { c = store.config } }
            .onChange(of: store.config?.name) { _, _ in c = store.config }
    }
}

private struct PermissionsPage: View {
    @ObservedObject var store: SettingsStore
    @State private var mode = "confirm"
    var body: some View {
        HUD.section("Permissions")
        Picker("System permission mode", selection: $mode) {
            Text("confirm").tag("confirm"); Text("allow").tag("allow")
        }.foregroundStyle(HUD.ink)
        Text("confirm — ask before risky actions.  allow — auto-approve everything.")
            .font(.system(size: 12)).foregroundStyle(HUD.inkDim)
        saveButton("Save mode") {
            var cfg = store.config; cfg?.permission_mode = mode
            if let v = cfg { Task { await store.saveConfig(v); await store.loadPermissions() } }
        }
        Spacer().frame(height: 10)
        HUD.section("Granted skills")
        if (store.permissions?.granted ?? []).isEmpty {
            Text("No skills have persistent access.").font(.system(size: 12)).foregroundStyle(HUD.inkDim)
        }
        ForEach(store.permissions?.granted ?? [], id: \.self) { skill in
            HStack {
                Text(skill).font(.system(size: 13)).foregroundStyle(HUD.ink)
                Spacer()
                Button { Task { await store.revoke(skill) } } label: {
                    Text("Revoke").font(.system(size: 12)).foregroundColor(.red)
                }.buttonStyle(.plain)
            }
        }
        Color.clear.frame(height: 1).onChange(of: store.permissions?.mode) { _, m in mode = m ?? "confirm" }
            .onAppear { mode = store.permissions?.mode ?? "confirm" }
    }
}
