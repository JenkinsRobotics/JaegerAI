//
//  OnboardingWindow.swift
//  JaegerOS / Onboarding
//
//  First-run setup, iOS-new-device style: one step per screen, progress
//  dots, big typography on the splash's dark canvas (Theme/Term). Shown
//  by AgentBridge when the bridge reports ``fatal kind=no_instance``;
//  drives the SAME Python setup core the CLI wizard uses, over the
//  bridge's additive v1 queries/commands:
//
//    query  characters       → the card grid
//    query  setup_defaults   → host tier + recommended model pair
//    command create_instance → writes the instance, then the bridge
//                              boots it (agent_state booting → ready is
//                              the live "Creating your Jaeger…" progress)
//
//  Window plumbing mirrors SplashWindowController — an NSWindow owned by
//  a tiny @MainActor controller, NOT a SwiftUI scene, so it can appear
//  before any scene and never touches the operator's MenuCard files.
//

import AppKit
import SwiftUI

@MainActor
final class OnboardingWindowController {
    static let shared = OnboardingWindowController()

    private var window: NSWindow?
    private var model: OnboardingModel?

    private init() {}

    func show(agent: AgentBridge) {
        if window != nil { return }
        let model = OnboardingModel(agent: agent)
        model.onFinished = { [weak self] in self?.close() }
        self.model = model

        let hosting = NSHostingView(rootView: OnboardingRootView(model: model))
        let panel = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 780, height: 560),
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        panel.contentView = hosting
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.isMovableByWindowBackground = true
        panel.level = .floating
        panel.center()
        panel.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        window = panel
        NSLog("[Onboarding] window shown")

        Task { await model.loadCatalog() }
    }

    func close() {
        window?.orderOut(nil)
        window = nil
        model = nil
        NSLog("[Onboarding] window closed")
    }
}

// MARK: - Model

@MainActor
final class OnboardingModel: ObservableObject {
    @Published var step: OnboardingStep = .welcome
    @Published var answers = OnboardingAnswers()
    @Published var characters: [OnboardingCharacter] = []
    @Published var defaults: SetupDefaults?
    /// "Use recommended" (default on). Advanced overrides live in
    /// ``answers.awakeModel`` / ``answers.asleepModel``; when this is on
    /// they're cleared so Python resolves the tier pick.
    @Published var useRecommended = true
    @Published var loading = true
    @Published var creationError: String?
    @Published var bootDetail = "Preparing…"

    let agent: AgentBridge
    var onFinished: (() -> Void)?

    init(agent: AgentBridge) {
        self.agent = agent
    }

    // MARK: catalog

    func loadCatalog() async {
        loading = true
        defer { loading = false }
        // Characters — same query the settings HUD uses; works pre-instance.
        let chars = await agent.query("characters")
        if chars.ok, let data = chars.json,
           let list = try? JSONDecoder().decode([OnboardingCharacter].self,
                                                from: data) {
            characters = list
        }
        let setup = await agent.query("setup_defaults")
        if setup.ok, let data = setup.json,
           let d = try? SetupDefaults.decode(data) {
            defaults = d
        }
        // Preselect the default character so Continue is never a dead end.
        if answers.characterId.isEmpty,
           let pick = characters.first(where: { $0.id == defaults?.defaultCharacter })
                    ?? characters.first {
            select(pick)
        }
    }

    func select(_ character: OnboardingCharacter) {
        answers.select(characterId: character.id,
                       name: character.name, role: character.role)
    }

    var selectedCharacter: OnboardingCharacter? {
        characters.first { $0.id == answers.characterId }
    }

    // MARK: navigation

    var canContinue: Bool {
        switch step {
        case .character: return answers.canCreate
        case .identity:
            return !answers.displayName
                .trimmingCharacters(in: .whitespaces).isEmpty
        default: return true
        }
    }

    func advance() {
        if step == .review {
            withAnimation(.easeInOut(duration: 0.3)) { step = .creating }
            Task { await create() }
            return
        }
        withAnimation(.easeInOut(duration: 0.3)) { step = step.next }
    }

    func back() {
        withAnimation(.easeInOut(duration: 0.3)) { step = step.previous }
    }

    // MARK: create

    func create() async {
        creationError = nil
        if useRecommended {
            answers.awakeModel = ""
            answers.asleepModel = ""
        }
        bootDetail = "Writing \(answers.displayName)'s instance…"
        let result = await agent.command("create_instance",
                                         args: answers.commandArgs())
        guard result.ok else {
            creationError = result.error ?? "create_instance failed"
            return
        }
        NSLog("[Onboarding] create_instance ok")
        // The bridge is now booting the fresh instance — agent_state
        // streams booting → ready. Ride it, exactly like the splash does.
        bootDetail = "Waking \(answers.displayName) — loading the model…"
        let bootingSeen = ContinuousClock.now
        while true {
            switch agent.agentState {
            case .ready:
                bootDetail = "\(answers.displayName) is online."
                await SettingsStore.shared.preload()
                withAnimation(.easeInOut(duration: 0.3)) { step = .done }
                NSLog("[Onboarding] boot ready — onboarding complete")
                return
            case .failed(let why):
                // Give the booting frame a beat to replace the stale
                // pre-create failed state before treating it as real.
                if ContinuousClock.now - bootingSeen > .seconds(5) {
                    creationError =
                        "\(answers.displayName) was created, but the first "
                        + "boot reported: \(why)"
                    NSLog("[Onboarding] boot failed: \(why)")
                    return
                }
            case .booting:
                break
            }
            try? await Task.sleep(for: .milliseconds(250))
        }
    }

    func finish() {
        agent.onboardingDidFinish()
        onFinished?()
    }
}

// MARK: - Root view

private struct OnboardingRootView: View {
    @ObservedObject var model: OnboardingModel

    var body: some View {
        VStack(spacing: 0) {
            header
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            footer
        }
        .frame(width: 780, height: 560)
        .background(background)
        .clipShape(RoundedRectangle(cornerRadius: 18))
        .overlay(RoundedRectangle(cornerRadius: 18)
            .stroke(Color.white.opacity(0.08), lineWidth: 1))
    }

    private var background: some View {
        ZStack {
            Term.canvas
            LinearGradient(
                colors: [Term.accent.opacity(0.14), .clear, .clear],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        }
    }

    private var header: some View {
        VStack(spacing: 14) {
            HStack(spacing: 10) {
                JaegerMechIcon(size: 22)
                Text("JAEGER OS SETUP")
                    .font(.system(size: 11, weight: .semibold))
                    .kerning(2.2)
                    .foregroundStyle(Term.inkDim)
                Spacer()
            }
            if OnboardingStep.dotted.contains(model.step) {
                HStack(spacing: 8) {
                    ForEach(OnboardingStep.dotted, id: \.self) { s in
                        Capsule()
                            .fill(s == model.step ? Term.accent
                                  : s < model.step ? Term.accent.opacity(0.45)
                                  : Color.white.opacity(0.14))
                            .frame(width: s == model.step ? 26 : 14, height: 4)
                            .animation(.easeInOut(duration: 0.25),
                                       value: model.step)
                    }
                    Spacer()
                    Text(model.step.title.uppercased())
                        .font(.system(size: 10, weight: .bold))
                        .kerning(1.6)
                        .foregroundStyle(Term.inkDim)
                }
            }
        }
        .padding(EdgeInsets(top: 22, leading: 30, bottom: 10, trailing: 30))
    }

    @ViewBuilder private var content: some View {
        ZStack {
            switch model.step {
            case .welcome: WelcomeStep()
            case .character: CharacterStep(model: model)
            case .identity: IdentityStep(model: model)
            case .model: ModelStep(model: model)
            case .permissions: PermissionsStep(model: model)
            case .review: ReviewStep(model: model)
            case .creating: CreatingStep(model: model)
            case .done: DoneStep(model: model)
            }
        }
        .padding(.horizontal, 30)
        .transition(.asymmetric(
            insertion: .move(edge: .trailing).combined(with: .opacity),
            removal: .move(edge: .leading).combined(with: .opacity)))
        .id(model.step)   // one view per step → clean cross-step animation
    }

    @ViewBuilder private var footer: some View {
        HStack {
            if model.step > .welcome && model.step <= .review {
                Button(action: { model.back() }) {
                    Text("Back")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(Term.inkDim)
                        .padding(.horizontal, 18)
                        .padding(.vertical, 9)
                }
                .buttonStyle(.plain)
            }
            Spacer()
            if model.step <= .review {
                Button(action: { model.advance() }) {
                    Text(continueLabel)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 26)
                        .padding(.vertical, 10)
                        .background(Capsule().fill(
                            model.canContinue ? Term.accent
                                              : Term.accent.opacity(0.3)))
                }
                .buttonStyle(.plain)
                .disabled(!model.canContinue)
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(EdgeInsets(top: 12, leading: 30, bottom: 22, trailing: 30))
    }

    private var continueLabel: String {
        switch model.step {
        case .welcome: return "Get Started"
        case .review: return "Create my Jaeger"
        default: return "Continue"
        }
    }
}

// MARK: - Steps

private struct WelcomeStep: View {
    var body: some View {
        VStack(spacing: 18) {
            Spacer()
            JaegerMechIcon(size: 72)
            Text("REAL-WORLD LOCAL AGENTIC AGENT FRAMEWORK")
                .font(.system(size: 11, weight: .semibold))
                .kerning(1.4)
                .foregroundStyle(Color.white.opacity(0.55))
            Text("Welcome to JAEGER OS")
                .font(.system(size: 38, weight: .heavy))
                .foregroundStyle(.white)
            Text("Let's build your Jaeger — a local agent that lives\n"
                 + "entirely on this machine. Six quick steps.")
                .font(.system(size: 14))
                .multilineTextAlignment(.center)
                .foregroundStyle(Term.inkDim)
            Spacer()
        }
    }
}

private struct CharacterStep: View {
    @ObservedObject var model: OnboardingModel
    private let columns =
        Array(repeating: GridItem(.flexible(), spacing: 14), count: 4)

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            StepTitle("Choose a character",
                      subtitle: "Your Jaeger plays this character — name, "
                               + "voice and persona come from the pick. "
                               + "Editable later in Studio.")
            if model.loading && model.characters.isEmpty {
                Spacer()
                HStack { Spacer(); ProgressView().controlSize(.small); Spacer() }
                Spacer()
            } else {
                ScrollView(showsIndicators: false) {
                    LazyVGrid(columns: columns, spacing: 14) {
                        ForEach(model.characters) { c in
                            CharacterCard(
                                character: c,
                                selected: c.id == model.answers.characterId
                            ) { model.select(c) }
                        }
                    }
                    .padding(.vertical, 4)
                }
            }
        }
    }
}

private struct CharacterCard: View {
    let character: OnboardingCharacter
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 0) {
                portrait
                    .frame(height: 96)
                    .frame(maxWidth: .infinity)
                    .clipped()
                VStack(spacing: 2) {
                    Text(character.name)
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(Term.ink)
                        .lineLimit(1)
                    Text(character.role)
                        .font(.system(size: 9))
                        .foregroundStyle(Term.inkDim)
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                        .frame(height: 24, alignment: .top)
                }
                .padding(EdgeInsets(top: 7, leading: 8, bottom: 8, trailing: 8))
            }
            .background(Term.panel)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10)
                .stroke(selected ? Term.accent : Color.white.opacity(0.08),
                        lineWidth: selected ? 2 : 1))
            .shadow(color: selected ? Term.accent.opacity(0.35) : .clear,
                    radius: 8)
        }
        .buttonStyle(.plain)
        .animation(.easeInOut(duration: 0.15), value: selected)
    }

    @ViewBuilder private var portrait: some View {
        if let path = character.card ?? character.icon,
           let image = NSImage(contentsOfFile: path) {
            Image(nsImage: image)
                .resizable()
                .scaledToFill()
        } else {
            ZStack {
                Term.canvas
                Text(String(character.name.prefix(1)))
                    .font(.system(size: 34, weight: .heavy))
                    .foregroundStyle(Term.accent.opacity(0.7))
            }
        }
    }
}

private struct IdentityStep: View {
    @ObservedObject var model: OnboardingModel

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            StepTitle("Identity",
                      subtitle: "Prefilled from "
                               + (model.selectedCharacter?.name ?? "the character")
                               + " — type over anything. The name also names "
                               + "the instance folder.")
            OnboardingField(label: "NAME", text: $model.answers.displayName,
                            prompt: "Jarvis")
            OnboardingField(label: "ROLE — WHAT DOES IT DO?",
                            text: $model.answers.role,
                            prompt: "general-purpose agentic assistant")
            Spacer()
        }
    }
}

private struct ModelStep: View {
    @ObservedObject var model: OnboardingModel
    @State private var showAdvanced = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            StepTitle("Model",
                      subtitle: tierLine)
            if let d = model.defaults {
                VStack(spacing: 10) {
                    ModelRow(title: "AWAKE — REAL-TIME CONVERSATION",
                             pick: d.awake)
                    ModelRow(title: "ASLEEP — DEEP THINK",
                             pick: d.asleep)
                }
                Toggle(isOn: $model.useRecommended) {
                    Text("Use recommended")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(Term.ink)
                }
                .toggleStyle(.switch)
                .tint(Term.accent)
                if !model.useRecommended {
                    DisclosureGroup(isExpanded: $showAdvanced) {
                        VStack(spacing: 10) {
                            OnboardingField(
                                label: "AWAKE — REGISTRY KEY OR .GGUF PATH",
                                text: $model.answers.awakeModel,
                                prompt: d.awake.key)
                            OnboardingField(
                                label: "ASLEEP — REGISTRY KEY OR .GGUF PATH",
                                text: $model.answers.asleepModel,
                                prompt: d.asleep.key)
                        }
                        .padding(.top, 8)
                    } label: {
                        Text("Advanced")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(Term.inkDim)
                    }
                    .onAppear { showAdvanced = true }
                }
            } else {
                Spacer()
                HStack { Spacer(); ProgressView().controlSize(.small); Spacer() }
            }
            Spacer()
        }
    }

    private var tierLine: String {
        guard let d = model.defaults else { return "Detecting this Mac…" }
        return String(format: "This Mac: %.0f GB unified memory → %@ tier.",
                      d.hostMemoryGb, d.tierLabel)
    }
}

private struct ModelRow: View {
    let title: String
    let pick: SetupDefaults.ModelPick

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.system(size: 9, weight: .bold))
                    .kerning(1.2)
                    .foregroundStyle(Term.inkDim)
                Text(pick.displayName)
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(Term.ink)
                Text(availability)
                    .font(.system(size: 11))
                    .foregroundStyle(pick.foundLocally
                                     ? Color(red: 0.35, green: 0.95, blue: 0.70)
                                     : Term.inkDim)
            }
            Spacer()
            Text(String(format: "%.1f GB", pick.sizeGb))
                .font(Term.mono)
                .foregroundStyle(Term.inkDim)
        }
        .padding(14)
        .background(Term.panel)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10)
            .stroke(Color.white.opacity(0.08), lineWidth: 1))
    }

    private var availability: String {
        pick.foundLocally
            ? "✓ found on this machine (\(pick.source ?? "local"))"
            : "will download on first use"
    }
}

private struct PermissionsStep: View {
    @ObservedObject var model: OnboardingModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            StepTitle("Permissions",
                      subtitle: "Some tools act on the world — run code, "
                               + "control the computer, install packages.")
            OptionCard(
                title: "Ask me before each action",
                detail: "Every world-touching tool call needs your approval. "
                       + "Recommended.",
                selected: model.answers.permissionMode == "confirm"
            ) { model.answers.permissionMode = "confirm" }
            OptionCard(
                title: "Auto-allow everything",
                detail: "For a trusted, unattended robot. The agent acts "
                       + "without asking.",
                selected: model.answers.permissionMode == "allow"
            ) { model.answers.permissionMode = "allow" }
            Spacer()
        }
    }
}

private struct OptionCard: View {
    let title: String
    let detail: String
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                Circle()
                    .stroke(selected ? Term.accent : Color.white.opacity(0.25),
                            lineWidth: 2)
                    .background(Circle()
                        .fill(selected ? Term.accent : .clear)
                        .padding(4))
                    .frame(width: 18, height: 18)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(Term.ink)
                    Text(detail)
                        .font(.system(size: 11))
                        .foregroundStyle(Term.inkDim)
                }
                Spacer()
            }
            .padding(16)
            .background(Term.panel)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10)
                .stroke(selected ? Term.accent : Color.white.opacity(0.08),
                        lineWidth: selected ? 2 : 1))
        }
        .buttonStyle(.plain)
        .animation(.easeInOut(duration: 0.15), value: selected)
    }
}

private struct ReviewStep: View {
    @ObservedObject var model: OnboardingModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            StepTitle("Review",
                      subtitle: "Everything can be changed later — "
                               + "in Settings or Jaeger Studio.")
            VStack(spacing: 0) {
                row("Character", model.selectedCharacter?.name
                        ?? model.answers.characterId)
                row("Name", model.answers.displayName)
                row("Role", model.answers.role)
                row("Awake model", model.useRecommended
                        ? recommended(\.awake) : model.answers.awakeModel)
                row("Asleep model", model.useRecommended
                        ? recommended(\.asleep) : model.answers.asleepModel)
                row("Permissions", model.answers.permissionMode == "confirm"
                        ? "ask before each action" : "auto-allow",
                    last: true)
            }
            .background(Term.panel)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10)
                .stroke(Color.white.opacity(0.08), lineWidth: 1))
            Spacer()
        }
    }

    private func recommended(
        _ path: KeyPath<SetupDefaults, SetupDefaults.ModelPick>) -> String {
        guard let d = model.defaults else { return "recommended" }
        return d[keyPath: path].displayName + "  (recommended)"
    }

    private func row(_ label: String, _ value: String,
                     last: Bool = false) -> some View {
        VStack(spacing: 0) {
            HStack {
                Text(label.uppercased())
                    .font(.system(size: 10, weight: .bold))
                    .kerning(1.2)
                    .foregroundStyle(Term.inkDim)
                    .frame(width: 130, alignment: .leading)
                Text(value)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Term.ink)
                    .lineLimit(1)
                Spacer()
            }
            .padding(EdgeInsets(top: 11, leading: 16, bottom: 11, trailing: 16))
            if !last { Term.rule.frame(height: 1).padding(.horizontal, 12) }
        }
    }
}

private struct CreatingStep: View {
    @ObservedObject var model: OnboardingModel

    var body: some View {
        VStack(spacing: 18) {
            Spacer()
            if let error = model.creationError {
                Text("Setup hit a wall")
                    .font(.system(size: 28, weight: .heavy))
                    .foregroundStyle(.white)
                Text(error)
                    .font(.system(size: 12))
                    .foregroundStyle(Color(red: 1.0, green: 0.48, blue: 0.42))
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 520)
                Button(action: { model.back() }) {
                    Text("Back")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 26)
                        .padding(.vertical, 10)
                        .background(Capsule().fill(Term.accent))
                }
                .buttonStyle(.plain)
            } else {
                ProgressView()
                    .controlSize(.large)
                    .tint(Term.accent)
                Text("Creating your Jaeger…")
                    .font(.system(size: 28, weight: .heavy))
                    .foregroundStyle(.white)
                Text(model.bootDetail)
                    .font(.system(size: 13))
                    .foregroundStyle(Term.inkDim)
                TimelineView(.periodic(from: .now, by: 4)) { context in
                    let idx = Int(context.date.timeIntervalSinceReferenceDate / 4)
                        % SplashQuips.all.count
                    Text(SplashQuips.all[idx])
                        .font(.system(size: 11, weight: .medium).italic())
                        .foregroundStyle(Color.white.opacity(0.4))
                }
            }
            Spacer()
        }
    }
}

private struct DoneStep: View {
    @ObservedObject var model: OnboardingModel

    var body: some View {
        VStack(spacing: 18) {
            Spacer()
            Circle()
                .fill(Color(red: 0.35, green: 0.95, blue: 0.70).opacity(0.16))
                .frame(width: 88, height: 88)
                .overlay(Image(systemName: "checkmark")
                    .font(.system(size: 38, weight: .heavy))
                    .foregroundStyle(Color(red: 0.35, green: 0.95, blue: 0.70)))
            Text("\(model.answers.displayName) is ready")
                .font(.system(size: 32, weight: .heavy))
                .foregroundStyle(.white)
            Text("All systems go. Find your Jaeger in the menu bar —\n"
                 + "or press ⌥Space anywhere.")
                .font(.system(size: 13))
                .multilineTextAlignment(.center)
                .foregroundStyle(Term.inkDim)
            Button(action: { model.finish() }) {
                Text("Start")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 34)
                    .padding(.vertical, 11)
                    .background(Capsule().fill(Term.accent))
            }
            .buttonStyle(.plain)
            .keyboardShortcut(.defaultAction)
            Spacer()
        }
    }
}

// MARK: - Shared bits

private struct StepTitle: View {
    let title: String
    let subtitle: String

    init(_ title: String, subtitle: String) {
        self.title = title
        self.subtitle = subtitle
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.system(size: 26, weight: .heavy))
                .foregroundStyle(.white)
            Text(subtitle)
                .font(.system(size: 12))
                .foregroundStyle(Term.inkDim)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.top, 6)
    }
}

private struct OnboardingField: View {
    let label: String
    @Binding var text: String
    let prompt: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label)
                .font(.system(size: 10, weight: .bold))
                .kerning(1.4)
                .foregroundStyle(Term.inkDim)
            TextField("", text: $text,
                      prompt: Text(prompt).foregroundStyle(
                          Term.inkDim.opacity(0.5)))
                .textFieldStyle(.plain)
                .font(.system(size: 16, weight: .medium))
                .foregroundStyle(Term.ink)
                .padding(EdgeInsets(top: 11, leading: 14,
                                    bottom: 11, trailing: 14))
                .background(Term.panel)
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .overlay(RoundedRectangle(cornerRadius: 10)
                    .stroke(Color.white.opacity(0.1), lineWidth: 1))
        }
    }
}
