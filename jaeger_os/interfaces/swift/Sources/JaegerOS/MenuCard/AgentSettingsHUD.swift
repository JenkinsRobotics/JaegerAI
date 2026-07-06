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
import UniformTypeIdentifiers

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
    @ObservedObject private var store = SettingsStore.shared
    @State private var tab: Tab = .home

    /// The AGENT's name (identity.yaml), never the character. ``store.detail``
    /// is the active CHARACTER's detail, so it must not lead here.
    private var name: String {
        agent.status?.agentName ?? agent.status?.character
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
            if tab != .library {
                agentPanel
            }
        }
        .background(HUD.bg)
        .task { await store.loadInitial() }
        .onChange(of: tab) { _, next in
            Task { await loadForTab(next) }
        }
    }

    @ViewBuilder private var page: some View {
        switch tab {
        case .home: HomePage(store: store, agent: agent, name: name)
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

    private func loadForTab(_ next: Tab) async {
        switch next {
        case .home, .library:
            if store.characters.isEmpty { await store.loadCharacters() }
        case .character, .traits:
            if store.detail == nil { await store.loadDetail() }
        case .app:
            if store.settingsGroups.isEmpty { await store.loadSettingsCatalog() }
        case .permissions:
            if store.permissions == nil { await store.loadPermissions() }
        }
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

@MainActor
private func saveButton(_ title: String, _ action: @escaping () -> Void) -> some View {
    Button(action: action) {
        Text(title).font(.system(size: 13, weight: .bold)).foregroundColor(Color(red: 0.02, green: 0.08, blue: 0.05))
            .padding(.horizontal, 18).padding(.vertical, 8)
            .background(RoundedRectangle(cornerRadius: 9).fill(HUD.accent))
    }.buttonStyle(.plain)
}

// MARK: - pages

/// The instance overview — the agent (identity.yaml) front and center: its
/// profile picture + name, the character it's PLAYING as a secondary
/// reference, and the instance settings the operator can change (name +
/// picture). The persona's characteristics stay below as a reference.
private struct HomePage: View {
    @ObservedObject var store: SettingsStore
    @ObservedObject var agent: AgentBridge
    let name: String
    @State private var draftName: String = ""
    @State private var didSeedName = false

    private var character: String? { agent.status?.character }
    private var model: String? { agent.status?.modelName }

    var body: some View {
        overview
        Spacer().frame(height: 10)
        instanceSettings
        Spacer().frame(height: 14)
        HUD.section("Persona — \(character ?? "…")")
        Text("The personality this instance is playing. Edit it in the "
             + "Character and Traits tabs; it never changes the agent's name.")
            .font(.system(size: 11)).foregroundStyle(HUD.inkDim)
        Spacer().frame(height: 6)
        let active = store.characters.first(where: { $0.active })
        ForEach(Array((active?.stats ?? [])
            .sorted { abs($0.val - 0.5) > abs($1.val - 0.5) }.prefix(6)),
                id: \.key) { s in
            traitRow(s.key, s.val)
        }
    }

    // Picture + name + "playing X" + model.
    private var overview: some View {
        HStack(alignment: .center, spacing: 18) {
            InstanceAvatar(path: agent.status?.iconPath, size: 76)
            VStack(alignment: .leading, spacing: 4) {
                Text(name).font(.system(size: 32, weight: .heavy))
                    .foregroundStyle(HUD.ink).lineLimit(1)
                if let character {
                    Text("playing \(character)")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(HUD.accent)
                }
                if let model {
                    Text(model).font(.system(size: 11)).foregroundStyle(HUD.inkDim)
                }
            }
            Spacer()
        }
    }

    // The editable instance settings: agent name + profile picture.
    private var instanceSettings: some View {
        VStack(alignment: .leading, spacing: 10) {
            HUD.section("Instance")
            HStack(alignment: .bottom, spacing: 10) {
                hudField("Agent name", $draftName)
                saveButton("Save") {
                    let n = draftName.trimmingCharacters(in: .whitespaces)
                    guard !n.isEmpty, n != name else { return }
                    Task { await store.saveAgentName(n) }
                }
            }
            HStack(spacing: 10) {
                Text("PROFILE PICTURE").font(.system(size: 10, weight: .semibold))
                    .tracking(1).foregroundStyle(HUD.inkDim)
                Spacer()
                Button("Change…") {
                    if let p = pickImageFile() { Task { await store.setAvatar(path: p) } }
                }.buttonStyle(.plain).foregroundStyle(HUD.accent)
                if agent.status?.hasCustomAvatar == true {
                    Button("Use character card") { Task { await store.clearAvatar() } }
                        .buttonStyle(.plain).foregroundStyle(HUD.inkDim)
                }
            }
            Text(agent.status?.hasCustomAvatar == true
                 ? "Using a custom picture."
                 : "Using \(character ?? "the character")'s card as the default.")
                .font(.system(size: 11)).foregroundStyle(HUD.inkDim)
        }
        .onAppear { if !didSeedName { draftName = name; didSeedName = true } }
        .onChange(of: name) { _, n in draftName = n }
    }
}

/// A circular avatar from a file path, with a mech-mark fallback.
private struct InstanceAvatar: View {
    let path: String?
    let size: CGFloat
    var body: some View {
        Group {
            if let path, let img = NSImage(contentsOfFile: path) {
                Image(nsImage: img).resizable().interpolation(.high).scaledToFill()
            } else {
                JaegerMechIcon(size: size)
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
        .overlay(Circle().stroke(HUD.stroke, lineWidth: 1))
    }
}

/// Native image picker for the profile picture. Returns the chosen file path.
@MainActor
private func pickImageFile() -> String? {
    let panel = NSOpenPanel()
    panel.allowedContentTypes = [.image]
    panel.allowsMultipleSelection = false
    panel.canChooseDirectories = false
    panel.prompt = "Choose"
    panel.message = "Choose a profile picture for this instance"
    return panel.runModal() == .OK ? panel.url?.path : nil
}

private struct LibraryPage: View {
    @ObservedObject var store: SettingsStore
    private let cols = [GridItem(.adaptive(minimum: 276, maximum: 276), spacing: 18)]
    var body: some View {
        HStack {
            HUD.section("Character Library")
            Text("· \(store.characters.count) characters")
                .font(.system(size: 12))
                .foregroundStyle(HUD.inkDim)
            Spacer()
        }
        LazyVGrid(columns: cols, spacing: 16) {
            ForEach(store.characters) { c in
                CharacterLibraryCard(character: c, store: store)
            }
        }
    }
}

private struct CharacterLibraryCard: View {
    let character: CharacterSummary
    @ObservedObject var store: SettingsStore

    private var artPath: String? { character.card ?? character.icon }
    private var topStats: [CharacterSummary.Stat] {
        Array(character.stats.sorted {
            abs($0.val - 0.5) > abs($1.val - 0.5)
        }.prefix(3))
    }

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            artwork
            LinearGradient(
                colors: [.black.opacity(0.0), .black.opacity(0.50), .black.opacity(0.90)],
                startPoint: .top,
                endPoint: .bottom
            )
            HStack {
                badge("rev \(String(format: "%.1f", character.revision))", muted: true)
                Spacer()
            }
            .padding(14)
            .frame(maxHeight: .infinity, alignment: .top)

            badge("Lv \(character.level)", muted: false)
                .padding(14)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)

            VStack(alignment: .leading, spacing: 7) {
                Text(character.name.uppercased())
                    .font(.system(size: 19, weight: .heavy))
                    .foregroundStyle(HUD.ink)
                    .lineLimit(1)
                Text(character.role.isEmpty ? "—" : character.role)
                    .font(.system(size: 11))
                    .foregroundStyle(Color(red: 0.79, green: 0.77, blue: 0.88))
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: 16) {
                    ForEach(topStats, id: \.key) { stat in
                        VStack(alignment: .leading, spacing: 0) {
                            Text(String(stat.key.prefix(4)).uppercased())
                                .font(.system(size: 9, weight: .bold))
                                .foregroundStyle(Color(red: 0.64, green: 0.62, blue: 0.75))
                            Text("\(Int((stat.val * 100).rounded()))")
                                .font(.system(size: 14, weight: .heavy))
                                .foregroundStyle(HUD.ink)
                        }
                    }
                }

                HStack(spacing: 8) {
                    cardButton(character.active ? "SELECTED" : "SELECT",
                               filled: true,
                               disabled: character.active) {
                        Task {
                            await store.select(character.id)
                            await maybeOfferCardAsPicture()
                        }
                    }
                    cardButton(character.bound ? "DEFAULT" : "MAKE DEFAULT",
                               filled: false,
                               disabled: character.bound) {
                        Task { await store.makeDefault(character.id) }
                    }
                }
                .padding(.top, 3)
            }
            .padding(16)
        }
        .frame(width: 276, height: 356)
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16)
            .stroke(character.active ? HUD.accent : HUD.stroke, lineWidth: character.active ? 2 : 1))
        .shadow(color: .black.opacity(0.25), radius: 14, x: 0, y: 8)
    }

    /// After a persona switch, OFFER to adopt this character's card as the
    /// profile picture — but ONLY if the operator set a custom one (otherwise
    /// the avatar already follows the card by default). Opt-in, never
    /// automatic: the default action keeps the existing picture.
    @MainActor private func maybeOfferCardAsPicture() async {
        guard AgentBridge.shared.status?.hasCustomAvatar == true,
              let card = artPath else { return }
        let a = NSAlert()
        a.messageText = "Now playing \(character.name)"
        a.informativeText = "Use \(character.name)'s picture as your profile "
            + "picture? Your current custom picture will be replaced."
        a.addButton(withTitle: "Use \(character.name)'s picture")
        a.addButton(withTitle: "Keep mine")
        if a.runModal() == .alertFirstButtonReturn {
            await store.setAvatar(path: card)
        }
    }

    @ViewBuilder private var artwork: some View {
        if let path = artPath, let image = NSImage(contentsOfFile: path) {
            Image(nsImage: image)
                .resizable()
                .scaledToFill()
                .frame(width: 276, height: 356)
        } else {
            LinearGradient(colors: [HUD.field, HUD.panel],
                           startPoint: .topLeading,
                           endPoint: .bottomTrailing)
        }
    }

    private func badge(_ text: String, muted: Bool) -> some View {
        Text(text)
            .font(.system(size: muted ? 10 : 11, weight: .bold))
            .foregroundStyle(muted ? HUD.inkDim : Color.black)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(Capsule().fill(muted ? Color.black.opacity(0.36) : HUD.accent))
    }

    private func cardButton(_ text: String, filled: Bool, disabled: Bool,
                            action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(text)
                .font(.system(size: 11, weight: .heavy))
                .lineLimit(1)
                .minimumScaleFactor(0.78)
                .foregroundStyle(filled ? Color.black : (disabled ? HUD.accent : HUD.ink))
                .frame(maxWidth: .infinity, minHeight: 34)
                .background(RoundedRectangle(cornerRadius: 8)
                    .fill(filled ? HUD.accent : Color.black.opacity(0.28)))
                .overlay(RoundedRectangle(cornerRadius: 8)
                    .stroke(disabled ? HUD.accent : (filled ? HUD.accent : HUD.stroke), lineWidth: 1))
        }
        .buttonStyle(.plain)
        .disabled(disabled)
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

/// The App Settings page — GENERICALLY rendered from the schema-derived
/// catalog. Nothing here names a field: every control comes from a
/// ``Setting`` descriptor the Python catalog produced, so a new setting is
/// one annotated ``Field`` in ``schemas.py`` and it appears here for free.
private struct AppPage: View {
    @ObservedObject var store: SettingsStore
    @State private var showAdvanced = false

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            HUD.section("App Settings")
            Spacer()
            if store.settingsRestartNeeded { restartBadge }
        }
        if let err = store.settingsError {
            Text(err).font(.system(size: 12)).foregroundStyle(Color.red)
        }
        if store.settingsGroups.isEmpty {
            Text("Loading…").foregroundStyle(HUD.inkDim)
        } else {
            ForEach(store.settingsGroups) { group in
                groupSection(group)
            }
            Toggle("Show advanced settings", isOn: $showAdvanced)
                .tint(HUD.accent).foregroundStyle(HUD.inkDim)
                .font(.system(size: 12)).padding(.top, 8)
        }
    }

    @ViewBuilder private func groupSection(_ group: SettingGroup) -> some View {
        let basic = group.settings.filter { !$0.advanced }
        let advanced = group.settings.filter { $0.advanced }
        let visible = showAdvanced ? group.settings : basic
        if !visible.isEmpty {
            Spacer().frame(height: 10)
            Text(group.name.uppercased())
                .font(.system(size: 10, weight: .bold)).tracking(2)
                .foregroundStyle(HUD.accent)
            ForEach(basic) { SettingRow(setting: $0, store: store) }
            if showAdvanced {
                ForEach(advanced) { SettingRow(setting: $0, store: store) }
            }
        }
    }

    private var restartBadge: some View {
        Text("RESTART REQUIRED")
            .font(.system(size: 9, weight: .bold)).tracking(1)
            .foregroundStyle(Color.black)
            .padding(.horizontal, 8).padding(.vertical, 3)
            .background(Capsule().fill(HUD.accent))
    }
}

/// One catalog descriptor, rendered by its ``type``. bool→Toggle,
/// enum→Picker(choices), int/float→numeric field, str→text field. Commits
/// through ``store.setSetting`` (validated by the schema on the Python side).
private struct SettingRow: View {
    let setting: Setting
    @ObservedObject var store: SettingsStore
    @State private var text = ""
    @State private var boolVal = false
    @State private var enumVal = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 8) {
                control
                if setting.restart {
                    Text("⟳").font(.system(size: 11)).foregroundStyle(HUD.accent)
                        .help("Restart required for this to take effect")
                }
                if setting.isOverridden {
                    Text("•").font(.system(size: 13)).foregroundStyle(HUD.accent)
                        .help("Changed from default")
                }
            }
            if !setting.description.isEmpty {
                Text(setting.description)
                    .font(.system(size: 11)).foregroundStyle(HUD.inkDim)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 3)
        .onAppear { sync() }
        .onChange(of: setting.current) { _, _ in sync() }
    }

    @ViewBuilder private var control: some View {
        switch setting.type {
        case "bool":
            Toggle(setting.label, isOn: Binding(
                get: { boolVal },
                set: { boolVal = $0; commit(.bool($0)) }))
                .tint(HUD.accent).foregroundStyle(HUD.ink)
        case "enum":
            HStack {
                Text(setting.label).foregroundStyle(HUD.ink)
                    .font(.system(size: 13))
                Spacer()
                Picker("", selection: Binding(
                    get: { enumVal },
                    set: { enumVal = $0; commit(.string($0)) })) {
                    ForEach(setting.choices ?? [], id: \.self) { Text($0).tag($0) }
                }.labelsHidden().tint(HUD.accent).frame(maxWidth: 180)
            }
        default:
            HStack {
                Text(setting.label).foregroundStyle(HUD.ink)
                    .font(.system(size: 13))
                Spacer()
                TextField("", text: $text, onCommit: commitText)
                    .textFieldStyle(.plain).multilineTextAlignment(.trailing)
                    .font(.system(size: 13)).foregroundStyle(HUD.ink)
                    .frame(maxWidth: 180).padding(6)
                    .background(RoundedRectangle(cornerRadius: 6).fill(HUD.field))
                    .overlay(RoundedRectangle(cornerRadius: 6)
                        .stroke(HUD.stroke, lineWidth: 1))
            }
        }
    }

    private func sync() {
        boolVal = setting.current.asBool
        enumVal = setting.current.asString
        text = setting.current.asString
    }

    private func commitText() {
        switch setting.type {
        case "int":
            if let i = Int(text.trimmingCharacters(in: .whitespaces)) {
                commit(.int(i))
            } else { commit(.string(text)) }   // let the schema reject it
        case "float":
            if let d = Double(text.trimmingCharacters(in: .whitespaces)) {
                commit(.double(d))
            } else { commit(.string(text)) }
        default:
            commit(.string(text))
        }
    }

    private func commit(_ value: SettingValue) {
        Task { await store.setSetting(setting.path, value) }
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
            Task {
                // permissions.mode is a schema field — persist it through the
                // SAME catalog everything else uses (no hardcoded save path).
                await store.setSetting("permissions.mode", .string(mode))
                await store.loadPermissions()
            }
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
