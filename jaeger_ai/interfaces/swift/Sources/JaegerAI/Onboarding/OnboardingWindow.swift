//
//  OnboardingWindow.swift
//  JaegerAI / Onboarding
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
private final class PersistentOnboardingWindow: NSWindow {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}

@MainActor
final class OnboardingWindowController {
    static let shared = OnboardingWindowController()

    private var window: NSWindow?
    private var model: OnboardingModel?

    private init() {}

    func show(agent: AgentBridge, suggestedName: String? = nil) {
        if let existing = window {
            existing.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        let model = OnboardingModel(agent: agent, suggestedName: suggestedName)
        model.onFinished = { [weak self] in self?.close() }
        self.model = model

        let hosting = NSHostingView(rootView: OnboardingRootView(model: model))
        let win = PersistentOnboardingWindow(
            contentRect: NSRect(x: 0, y: 0, width: 840, height: 660),
            styleMask: [.titled, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        win.title = "OS 1 Setup"
        win.titlebarAppearsTransparent = true
        win.titleVisibility = .hidden
        win.contentView = hosting
        win.isOpaque = false
        win.backgroundColor = .clear
        win.hasShadow = true
        win.isMovableByWindowBackground = true
        win.isReleasedWhenClosed = false
        win.hidesOnDeactivate = false
        win.collectionBehavior = [.moveToActiveSpace, .fullScreenAuxiliary]

        win.standardWindowButton(.closeButton)?.isHidden = true
        win.standardWindowButton(.miniaturizeButton)?.isHidden = true
        win.standardWindowButton(.zoomButton)?.isHidden = true

        win.center()
        win.makeKeyAndOrderFront(nil)
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        window = win
        NSLog("[Onboarding] persistent window shown")

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
    @Published var modelMatrix: ModelMatrixPayload?
    @Published var calibratingProvider: ModelProvider?
    @Published var calibrationKey: String = ""
    @Published var calibrationError: String?
    @Published var isCalibrating: Bool = false
    @Published var selectedProviderFilter: String = "all"
    @Published var useRecommended = false
    @Published var loading = true
    @Published var catalogError: String?
    @Published var creationError: String?
    @Published var bootDetail = "Preparing…"
    @Published var saveStatus: String?
    @Published var isSavingConfig: Bool = false
    @Published var guideText: String = ""
    @Published var guideModel: String = ""
    @Published var firstContactTurn: FirstBootGate.Turn?
    @Published var firstBootGate: FirstBootGate?

    private var narratedStep: OnboardingStep?

    let agent: AgentBridge
    var onFinished: (() -> Void)?

    init(agent: AgentBridge, suggestedName: String? = nil) {
        self.agent = agent
        if let suggestedName, !suggestedName.isEmpty {
            answers.pinnedName = suggestedName
            answers.displayName = suggestedName
        }
    }

    // MARK: catalog

    func loadCatalog() async {
        loading = true
        catalogError = nil
        defer { loading = false }
        guard agent.isConnected else {
            catalogError = agent.lastError ?? "Setup could not connect. Close the other JaegerAI app and retry."
            return
        }
        let result = await agent.query("onboarding_model_matrix")
        guard result.ok, let data = result.json else {
            catalogError = result.error ?? "The model catalog could not be loaded."
            return
        }
        do {
            let matrix = try ModelMatrixPayload.decode(data)
            modelMatrix = matrix
            NSLog("[Onboarding] catalog ready: \(matrix.providers.count) providers, \(matrix.models.count) models, configured=\(matrix.configured != nil)")
            if answers.awakeModel.isEmpty, let configured = matrix.configured {
                answers.awakeModel = configured.primaryModel
                answers.awakeProvider = configured.primaryProvider
            } else if answers.awakeModel.isEmpty,
                      let recommended = matrix.models.first(where: { $0.isRecommendedPrimary }) {
                // OS 1 chooses a host-appropriate starting point. The model
                // screen keeps the full manual provider/model controls.
                answers.awakeModel = recommended.id
                answers.awakeProvider = recommended.provider
                useRecommended = true
            }
            let chars = await agent.query("characters")
            guard chars.ok, let charsData = chars.json else {
                throw FirstBootGate.Failure(message: chars.error ?? "Could not load characters")
            }
            characters = try JSONDecoder().decode([OnboardingCharacter].self, from: charsData)
            let setup = await agent.query("setup_defaults")
            guard setup.ok, let setupData = setup.json else {
                throw FirstBootGate.Failure(message: setup.error ?? "Could not load setup defaults")
            }
            defaults = try SetupDefaults.decode(setupData)
            if answers.characterId.isEmpty {
                let identityResult = await agent.query("onboarding_identity")
                if identityResult.ok, let identityData = identityResult.json,
                   let saved = try JSONSerialization.jsonObject(with: identityData) as? [String: String] {
                    let characterID = saved["character_id"] ?? "assistant"
                    let characterName = characters.first(where: { $0.id == characterID })?.name
                        ?? "Assistant"
                    answers.characterId = characterID
                    answers.displayName = saved["display_name"] ?? characterName
                    answers.role = saved["role"] ?? ""
                    answers.voiceId = saved["voice_id"] ?? ""
                    answers.voiceProfile = saved["voice_profile"] ?? "female"
                    answers.interactionPosture = saved["interaction_posture"] ?? "attentive"
                } else if let character = characters.first(where: { $0.id == "assistant" }) ?? characters.first {
                    select(character)
                }
            }
        } catch {
            catalogError = "Could not read the model catalog: \(error.localizedDescription)"
            NSLog("[Onboarding] catalog decode failed: \(error)")
        }
    }

    func loadGuide(for requestedStep: OnboardingStep) async {
        guard requestedStep <= .review, narratedStep != requestedStep else { return }
        let facts: [String: any Sendable] = [
            "host_memory_gb": defaults?.hostMemoryGb ?? 0,
            "host_tier": defaults?.tierLabel ?? "detecting",
            "selected_provider": answers.awakeProvider,
            "selected_model": answers.awakeModel,
            "agent_name": answers.displayName,
        ]
        let result = await agent.query("onboarding_guide", args: [
            "step": requestedStep.title.lowercased().replacingOccurrences(of: " ", with: "_"),
            "facts": facts,
        ])
        guard step == requestedStep, result.ok, let data = result.json,
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let text = object["text"] as? String, !text.isEmpty else { return }
        guideText = text
        guideModel = object["model"] as? String ?? ""
        narratedStep = requestedStep
        let tts = TTSManager.shared
        tts.enterVoiceStage(.installer)
        tts.speak(text)
    }

    func selectProvider(_ provider: String) {
        useRecommended = false
        answers.awakeProvider = provider
        answers.awakeModel = ""
        saveStatus = nil
    }

    func selectModel(_ entry: DiscoveredModelEntry) {
        useRecommended = entry.isRecommendedPrimary
        answers.awakeProvider = entry.provider
        answers.awakeModel = entry.id
        saveStatus = nil
    }

    func applyRecommendation() {
        guard let recommended = modelMatrix?.models.first(where: { $0.isRecommendedPrimary }) else { return }
        answers.awakeProvider = recommended.provider
        answers.awakeModel = recommended.id
        useRecommended = true
        saveStatus = "Recommended for this Mac"
    }

    func updateConfiguredStack(
        primaryModel: String? = nil,
        primaryProvider: String? = nil,
        fallbackModel: String? = nil,
        fallbackProvider: String? = nil,
        coderModel: String? = nil,
        ttsVoice: String? = nil,
        sttFastModel: String? = nil,
        sttAccurateModel: String? = nil
    ) async {
        isSavingConfig = true
        saveStatus = nil
        defer { isSavingConfig = false }

        var args: [String: String] = [:]
        if let pm = primaryModel {
            args["primary_model"] = pm
            answers.awakeModel = pm
        }
        if let pp = primaryProvider { args["primary_provider"] = pp }
        if let fm = fallbackModel {
            args["fallback_model"] = fm
            answers.asleepModel = fm
        }
        if let fp = fallbackProvider { args["fallback_provider"] = fp }
        if let cm = coderModel { args["coder_model"] = cm }
        if let tv = ttsVoice { args["tts_voice"] = tv }
        if let sf = sttFastModel { args["stt_fast_model"] = sf }
        if let sa = sttAccurateModel { args["stt_accurate_model"] = sa }

        if let pp = primaryProvider { answers.awakeProvider = pp }
        saveStatus = "Selected. Applied when you start your OS."
    }

    func calibrate(provider: ModelProvider, apiKey: String) async {
        let trimmed = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            calibrationError = "API key cannot be empty"
            return
        }
        isCalibrating = true
        calibrationError = nil
        defer { isCalibrating = false }
        let res = await agent.command("calibrate_provider", args: [
            "provider": provider.id,
            "api_key": trimmed
        ])
        if res.ok {
            calibratingProvider = nil
            calibrationKey = ""
            let refreshed = await agent.query("onboarding_model_matrix")
            if refreshed.ok, let data = refreshed.json,
               let matrix = try? ModelMatrixPayload.decode(data) {
                modelMatrix = matrix
            }
        } else {
            calibrationError = res.error ?? "Failed to configure provider"
        }
    }

    func select(_ character: OnboardingCharacter) {
        answers.select(characterId: character.id,
                       name: character.name, role: character.role)
        if character.id == "assistant" {
            answers.setupPath = "custom_test"
            answers.voiceId = ""
            if answers.voiceProfile.isEmpty { answers.voiceProfile = "female" }
            if answers.interactionPosture.isEmpty { answers.interactionPosture = "attentive" }
            if !answers.displayNameEdited && answers.pinnedName.isEmpty {
                answers.displayName = character.name.isEmpty ? "Assistant" : character.name
            }
        } else {
            answers.setupPath = "preset"
            answers.voiceProfile = ""
            answers.interactionPosture = ""
            answers.voiceId = character.voiceId ?? ""
        }
    }

    var selectedCharacter: OnboardingCharacter? {
        characters.first { $0.id == answers.characterId }
    }

    func currentPrimaryModel() -> DiscoveredModelEntry? {
        let key = answers.awakeModel.isEmpty ? (modelMatrix?.recommendedPrimaryKey ?? "") : answers.awakeModel
        return modelMatrix?.models.first { $0.id == key && $0.provider == answers.awakeProvider }
    }

    func currentFallbackModel() -> DiscoveredModelEntry? {
        let key = answers.asleepModel.isEmpty ? (modelMatrix?.recommendedFallbackKey ?? "") : answers.asleepModel
        return modelMatrix?.models.first { $0.id == key }
    }

    // MARK: navigation

    var canContinue: Bool {
        guard !loading, catalogError == nil, modelMatrix != nil else { return false }
        if step == .character && answers.characterId.isEmpty { return false }
        if step == .identity && answers.displayName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return false }
        if step == .model || step == .review {
            guard !answers.awakeProvider.isEmpty,
                  !answers.awakeModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return false }
            let provider = modelMatrix?.providers.first { $0.id == answers.awakeProvider }
            return provider?.status != "needs_key"
        }
        return true
    }

    var dottedSteps: [OnboardingStep] {
        var steps: [OnboardingStep] = [.welcome, .architecture, .character]
        if answers.characterId == "assistant" { steps.append(.calibration) }
        return steps + [.identity, .model, .permissions, .review, .firstContact]
    }

    func advance() {
        guard canContinue else { return }
        if step == .review {
            step = .creating
            Task { await create() }
        } else if let index = dottedSteps.firstIndex(of: step), index + 1 < dottedSteps.count {
            guideText = ""
            step = dottedSteps[index + 1]
        }
    }

    func back() {
        creationError = nil
        if step == .creating { step = .review; return }
        if let index = dottedSteps.firstIndex(of: step), index > 0 {
            guideText = ""
            step = dottedSteps[index - 1]
        }
    }

    // MARK: create

    private var canStart: Bool {
        modelMatrix != nil && catalogError == nil && !answers.awakeProvider.isEmpty
            && !answers.awakeModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    func create() async {
        creationError = nil
        guard canStart else {
            creationError = "Choose a provider and model before starting your OS."
            return
        }
        bootDetail = "Saving your model selection…"
        let result = await agent.command("complete_setup", args: answers.commandArgs())
        guard result.ok else {
            creationError = result.error ?? "Could not save setup"
            return
        }
        NSLog("[Onboarding] setup saved — starting selected model")
        // The bridge is now booting the fresh instance — agent_state
        // streams booting → ready. Ride it, exactly like the splash does.
        bootDetail = "Waking \(answers.displayName) — loading the model…"
        let bootingSeen = ContinuousClock.now
        while true {
            if ContinuousClock.now - bootingSeen > .seconds(180) {
                creationError = "The selected model has not become ready. Check its provider connection and try again."
                return
            }
            switch agent.agentState {
            case .ready:
                bootDetail = "\(answers.displayName) is online."
                agent.onboardingRuntimeReady()
                let gate = FirstBootGate(bridge: agent)
                switch await gate.evaluate() {
                case .onboard(let turn):
                    firstBootGate = gate
                    firstContactTurn = turn
                    step = .firstContact
                    NSLog("[Onboarding] boot ready — continuing into first contact")
                case .proceed:
                    finish()
                    ChatWindowController.show(agent: agent)
                case .unavailable(let reason):
                    creationError = reason
                }
                return
            case .failed(let why):
                // Give the booting frame a beat to replace the stale
                // pre-create failed state before treating it as real.
                if ContinuousClock.now - bootingSeen > .seconds(5) {
                    creationError =
                        "The selected model could not start: \(why)"
                    NSLog("[Onboarding] boot failed: \(why)")
                    return
                }
            case .booting:
                break
            }
            try? await Task.sleep(for: .milliseconds(250))
        }
    }

    func replayInitiation() async {
        let result = await agent.command("first_boot_reset")
        guard result.ok else {
            creationError = result.error ?? "Could not restart initiation."
            return
        }
        finish()
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
            if model.step <= .review, !model.guideText.isEmpty {
                SetupGuideBar(text: model.guideText, modelName: model.guideModel)
                    .padding(.horizontal, 30)
                    .padding(.bottom, 8)
            }
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            footer
        }
        .frame(width: 840, height: 660)
        .background(background)
        .clipShape(RoundedRectangle(cornerRadius: 18))
        .overlay(RoundedRectangle(cornerRadius: 18)
            .stroke(Color.white.opacity(0.08), lineWidth: 1))
        .task(id: model.step) {
            await model.loadGuide(for: model.step)
        }
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
                Text("JENKINS ROBOTICS · OS 1 SETUP")
                    .font(.system(size: 11, weight: .semibold))
                    .kerning(2.2)
                    .foregroundStyle(Term.inkDim)
                Spacer()
            }
            let steps = model.dottedSteps
            if steps.contains(model.step) {
                HStack(spacing: 8) {
                    ForEach(steps, id: \.self) { s in
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
            case .welcome: WelcomeStep(model: model)
            case .architecture: ArchitectureStep()
            case .character: CharacterStep(model: model)
            case .calibration: CalibrationStep(model: model)
            case .identity: IdentityStep(model: model)
            case .model: ModelStep(model: model)
            case .permissions: PermissionsStep(model: model)
            case .review: ReviewStep(model: model)
            case .creating: CreatingStep(model: model)
            case .firstContact:
                if let gate = model.firstBootGate,
                   let turn = model.firstContactTurn {
                    FirstBootView(gate: gate, firstTurn: turn) {
                        model.finish()
                    }
                } else {
                    ProgressView("Preparing first contact…")
                }
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
        case .welcome: return "Begin Setup"
        case .review: return "Start OS 1"
        default: return "Continue"
        }
    }
}

private struct SetupGuideBar: View {
    let text: String
    let modelName: String

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "waveform.circle.fill")
                .foregroundStyle(Term.accent)
                .font(.system(size: 17))
            VStack(alignment: .leading, spacing: 3) {
                Text("SYSTEM GUIDE")
                    .font(.system(size: 9, weight: .bold))
                    .kerning(1.2)
                    .foregroundStyle(Term.accent)
                Text(text)
                    .font(.system(size: 11.5))
                    .foregroundStyle(Term.ink)
                    .lineLimit(3)
            }
            Spacer(minLength: 8)
            if !modelName.isEmpty {
                Text("OFFLINE")
                    .font(.system(size: 8, weight: .bold))
                    .foregroundStyle(Term.inkDim)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 3)
                    .background(Color.white.opacity(0.05))
                    .clipShape(Capsule())
            }
        }
        .padding(10)
        .background(Term.panel.opacity(0.86))
        .clipShape(RoundedRectangle(cornerRadius: 9))
        .overlay(RoundedRectangle(cornerRadius: 9)
            .stroke(Term.accent.opacity(0.22), lineWidth: 1))
    }
}

// MARK: - Steps

struct OS1WelcomeHero: View {
    var body: some View {
        VStack(spacing: 20) {
            Spacer()
            ZStack {
                Circle()
                    .fill(Term.accent.opacity(0.12))
                    .frame(width: 88, height: 88)
                Circle()
                    .stroke(Term.accent.opacity(0.32), lineWidth: 1.5)
                    .frame(width: 88, height: 88)
                JaegerMechIcon(size: 50)
            }

            VStack(spacing: 6) {
                Text("JENKINS ROBOTICS")
                    .font(.system(size: 11, weight: .bold))
                    .kerning(3.2)
                    .foregroundStyle(Term.accent)

                Text("OS 1")
                    .font(.system(size: 44, weight: .heavy))
                    .foregroundStyle(.white)
            }

            VStack(spacing: 8) {
                Text("An intuitive intelligence, living natively on your Mac.")
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(.white.opacity(0.92))

                Text("Not just a collection of apps or a chat window, but an active presence\nbuilt to listen, adapt to your daily rhythm, and execute real tasks on your Mac.\nAn open foundation engineered for both local neural engines and frontier cloud models.")
                    .font(.system(size: 13))
                    .multilineTextAlignment(.center)
                    .foregroundStyle(Term.inkDim)
                    .lineSpacing(4)
            }
            .frame(maxWidth: 580)
            Spacer()
        }
    }
}

private struct WelcomeStep: View {
    @ObservedObject var model: OnboardingModel

    var body: some View {
        VStack(spacing: 20) {
            OS1WelcomeHero()
            if model.loading {
                ProgressView("Loading providers and configured models…")
            }
            if let error = model.catalogError {
                Text(error).foregroundStyle(.red)
                Button("Retry") { Task { await model.loadCatalog() } }
            }
        }
    }
}

private struct ArchitectureStep: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            StepTitle("The Architecture",
                      subtitle: "A continuous local cognitive engine, engineered differently from ordinary chat tools.")

            HStack(alignment: .top, spacing: 14) {
                ArchitecturePillarCard(
                    badge: "CONTINUOUS PRESENCE",
                    icon: "waveform.circle.fill",
                    title: "What is the Assistant?",
                    description: "Rather than a temporary chat prompt in a browser, the Assistant runs as an integrated system daemon on macOS. It preserves memory across restarts, listens with natural voice VAD, and executes operations directly via the menu bar or ⌥Space."
                )

                ArchitecturePillarCard(
                    badge: "DUAL-STAGE COGNITION",
                    icon: "bolt.horizontal.circle.fill",
                    title: "How It Works",
                    description: "OS 1 organizes cognition into two cycles. While awake, streaming models handle conversational dialogue and local tool execution. While asleep, background consolidation passes reflect on interactions, update your relationship graph, and index memory."
                )

                ArchitecturePillarCard(
                    badge: "MODEL FREEDOM",
                    icon: "cpu.fill",
                    title: "Why It's Different",
                    description: "Your session state, voice processing, and tool execution remain anchored locally on your Mac via UNIX domain sockets (AF_UNIX). You choose your neural backend — run 100% offline via local Ollama weights, or connect frontier cloud models for deep reasoning."
                )
            }
            .padding(.top, 4)

            Spacer()
        }
    }
}

struct ArchitecturePillarCard: View {
    let badge: String
    let icon: String
    let title: String
    let description: String
    var compact: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: compact ? 8 : 12) {
            HStack {
                ZStack {
                    RoundedRectangle(cornerRadius: 10)
                        .fill(Term.accent.opacity(0.16))
                        .frame(width: compact ? 32 : 38, height: compact ? 32 : 38)
                    Image(systemName: icon)
                        .font(.system(size: compact ? 15 : 18, weight: .semibold))
                        .foregroundStyle(Term.accent)
                }
                Spacer()
                Text(badge)
                    .font(.system(size: 8, weight: .heavy))
                    .kerning(1.1)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 3)
                    .background(Capsule().fill(Color.white.opacity(0.06)))
                    .foregroundStyle(Term.inkDim)
            }

            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(.system(size: compact ? 13 : 14, weight: .bold))
                    .foregroundStyle(Term.ink)

                Text(description)
                    .font(.system(size: compact ? 11 : 11.5))
                    .foregroundStyle(Term.inkDim)
                    .lineSpacing(3.5)
                    .lineLimit(compact ? 5 : nil)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 0)
        }
        .padding(compact ? 12 : 16)
        .frame(maxWidth: .infinity, maxHeight: compact ? 196 : 310, alignment: .topLeading)
        .background(Term.panel)
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14)
            .stroke(Color.white.opacity(0.07), lineWidth: 1))
    }
}

private struct CharacterStep: View {
    @ObservedObject var model: OnboardingModel
    private let columns =
        Array(repeating: GridItem(.flexible(), spacing: 14), count: 4)

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            StepTitle("Choose an Architecture",
                      subtitle: "Select the OS 1 Assistant to personalize your setup via guided Q&A, or choose a pre-configured character.")

            if model.loading && model.characters.isEmpty {
                Spacer()
                HStack { Spacer(); ProgressView().controlSize(.small); Spacer() }
                Spacer()
            } else {
                ScrollView(showsIndicators: true) {
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
                if let selected = model.selectedCharacter {
                    CharacterProfilePreview(character: selected)
                }
            }
        }
    }
}

private struct CalibrationStep: View {
    @ObservedObject var model: OnboardingModel

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            StepTitle("OS 1 Calibration",
                      subtitle: "A quick diagnostic Q&A to tune your Assistant's acoustic profile and conversational posture.")

            VStack(alignment: .leading, spacing: 10) {
                Text("ACOUSTIC VOICE PROFILE")
                    .font(.system(size: 10, weight: .bold))
                    .kerning(1.4)
                    .foregroundStyle(Term.inkDim)

                HStack(spacing: 14) {
                    OS1OptionCard(
                        title: "Female Voice",
                        subtitle: "Warm, attentive, natural cadence\n(Samantha / Kokoro af_heart)",
                        icon: "waveform.circle.fill",
                        selected: model.answers.voiceProfile == "female"
                    ) {
                        model.answers.voiceProfile = "female"
                    }

                    OS1OptionCard(
                        title: "Male Voice",
                        subtitle: "Even-keeled, grounded, calm delivery\n(Daniel / Kokoro am_michael)",
                        icon: "waveform.circle",
                        selected: model.answers.voiceProfile == "male"
                    ) {
                        model.answers.voiceProfile = "male"
                    }
                }
            }

            VStack(alignment: .leading, spacing: 10) {
                Text("CONVERSATIONAL POSTURE")
                    .font(.system(size: 10, weight: .bold))
                    .kerning(1.4)
                    .foregroundStyle(Term.inkDim)

                HStack(spacing: 14) {
                    OS1OptionCard(
                        title: "Attentive & Empathetic",
                        subtitle: "Fluid pacing, conversational cadence, empathetic feedback",
                        icon: "person.wave.2.fill",
                        selected: model.answers.interactionPosture == "attentive"
                    ) {
                        model.answers.interactionPosture = "attentive"
                    }

                    OS1OptionCard(
                        title: "Pragmatic & Focused",
                        subtitle: "Direct, succinct execution, boundary-respecting and rapid",
                        icon: "bolt.shield.fill",
                        selected: model.answers.interactionPosture == "pragmatic"
                    ) {
                        model.answers.interactionPosture = "pragmatic"
                    }
                }
            }

            Spacer()
        }
    }
}

struct OS1OptionCard: View {
    let title: String
    let subtitle: String
    let icon: String
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 18))
                    .foregroundStyle(selected ? Term.accent : Term.inkDim)
                    .frame(width: 26)

                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(Term.ink)
                    Text(subtitle)
                        .font(.system(size: 10))
                        .foregroundStyle(Term.inkDim)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Term.panel)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10)
                .stroke(selected ? Term.accent : Color.white.opacity(0.06),
                        lineWidth: selected ? 2 : 1))
            .shadow(color: selected ? Term.accent.opacity(0.2) : .clear, radius: 6)
        }
        .buttonStyle(.plain)
    }
}

struct CharacterCard: View {
    let character: OnboardingCharacter
    let selected: Bool
    let action: () -> Void

    var isOS1: Bool { character.id == "assistant" }

    var body: some View {
        Button(action: action) {
            VStack(spacing: 0) {
                portrait
                    .clipped()

                VStack(spacing: 2) {
                    HStack(spacing: 4) {
                        Text(isOS1 ? "OS 1 Assistant" : character.name)
                            .font(.system(size: 11.5, weight: .bold))
                            .foregroundStyle(Term.ink)
                            .lineLimit(1)
                        if isOS1 {
                            Text("Q&A")
                                .font(.system(size: 7.5, weight: .heavy))
                                .kerning(0.8)
                                .padding(.horizontal, 4)
                                .padding(.vertical, 1.5)
                                .background(Capsule().fill(Term.accent.opacity(0.25)))
                                .foregroundStyle(Term.accent)
                        }
                    }

                    Text(isOS1 ? "Adaptive setup — calibrated via guided Q&A" : character.role)
                        .font(.system(size: 9.5))
                        .foregroundStyle(isOS1 ? Term.accent.opacity(0.85) : Term.inkDim)
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                        .frame(height: 24, alignment: .top)
                }
                .padding(EdgeInsets(top: 7, leading: 6, bottom: 8, trailing: 6))
            }
            .background(Term.panel)
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12)
                .stroke(selected ? Term.accent : (isOS1 ? Term.accent.opacity(0.3) : Color.white.opacity(0.08)),
                        lineWidth: selected ? 2 : 1))
            .shadow(color: selected ? Term.accent.opacity(0.35) : .clear,
                    radius: 8)
        }
        .buttonStyle(.plain)
        .animation(.easeInOut(duration: 0.15), value: selected)
        .help(character.description ?? character.role)
    }

    @ViewBuilder private var portrait: some View {
        if isOS1 {
            Color.clear
                .aspectRatio(320.0 / 420.0, contentMode: .fit)
                .overlay(
                    ZStack {
                        LinearGradient(
                            colors: [Term.accent.opacity(0.25), Term.canvas],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                        Circle()
                            .stroke(Term.accent.opacity(0.4), lineWidth: 1.5)
                            .frame(width: 58, height: 58)
                        Circle()
                            .fill(Term.accent.opacity(0.2))
                            .frame(width: 44, height: 44)
                        Image(systemName: "waveform.path")
                            .font(.system(size: 24, weight: .semibold))
                            .foregroundStyle(Term.accent)
                    }
                )
                .clipped()
        } else if let path = character.card ?? character.icon,
           let image = NSImage(contentsOfFile: path) {
            Image(nsImage: image)
                .resizable()
                .aspectRatio(320.0 / 420.0, contentMode: .fit)
        } else {
            Color.clear
                .aspectRatio(320.0 / 420.0, contentMode: .fit)
                .overlay(
                    ZStack {
                        Term.canvas
                        Text(String(character.name.prefix(1)))
                            .font(.system(size: 34, weight: .heavy))
                            .foregroundStyle(Term.accent.opacity(0.7))
                    }
                )
                .clipped()
        }
    }
}

struct CharacterProfilePreview: View {
    let character: OnboardingCharacter

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                Text(character.id == "assistant" ? "OS 1 Assistant" : character.name)
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Term.ink)
                Spacer()
                Text(character.id == "assistant" ? "GUIDED CALIBRATION" : "READY-MADE PROFILE")
                    .font(.system(size: 8, weight: .heavy))
                    .kerning(1.0)
                    .foregroundStyle(Term.accent)
            }
            if let description = character.description, !description.isEmpty {
                Text(description)
                    .font(.system(size: 11))
                    .foregroundStyle(Term.inkDim)
            }
            if character.id != "assistant",
               let backstory = character.backstory, !backstory.isEmpty {
                Text("Background: \(backstory)")
                    .font(.system(size: 10.5))
                    .foregroundStyle(Term.inkDim)
                    .lineLimit(3)
            }
            ForEach(character.highlights ?? [], id: \.self) { line in
                Text(line)
                    .font(.system(size: 10.5))
                    .foregroundStyle(Term.inkDim)
                    .lineLimit(2)
            }
            Text(character.id == "assistant"
                 ? "You will answer the personality and voice questions next."
                 : "This preset already includes its voice, mindset, behavior, and backstory. No personality interview follows.")
                .font(.system(size: 10.5, weight: .medium))
                .foregroundStyle(Term.accent.opacity(0.9))
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).fill(Term.accent.opacity(0.07)))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Term.accent.opacity(0.25)))
    }
}

private struct IdentityStep: View {
    @ObservedObject var model: OnboardingModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            StepTitle("Identity & Directives",
                      subtitle: "Set up who you are, what to call your agent, "
                               + "and your governing prime directives.")
            OnboardingField(label: "YOUR NAME (OPERATOR)",
                            text: $model.answers.userName,
                            prompt: "Matthew")
            OnboardingField(label: "AGENT NAME", text: nameBinding,
                            prompt: "ARES")
            OnboardingField(label: "ROLE — WHAT DOES IT DO?",
                            text: $model.answers.role,
                            prompt: "general-purpose autonomous executive assistant")
            OnboardingField(label: "CUSTOM PRIME DIRECTIVE (OPTIONAL)",
                            text: $model.answers.customPrimeDirective,
                            prompt: "e.g. Always prioritize concise execution and verify file edits")
            Spacer()
        }
    }

    /// Any edit here marks the field "touched" so a later character pick
    /// (Back → pick a different card → Continue) never clobbers it — an
    /// operator's own typing always wins (the operator contract).
    private var nameBinding: Binding<String> {
        Binding(
            get: { model.answers.displayName },
            set: {
                model.answers.displayName = $0
                model.answers.displayNameEdited = true
            }
        )
    }
}

private struct ModelStep: View {
    @ObservedObject var model: OnboardingModel
    @State private var showManual = false

    private var provider: ModelProvider? {
        model.modelMatrix?.providers.first { $0.id == model.answers.awakeProvider }
    }
    private var choices: [DiscoveredModelEntry] {
        model.modelMatrix?.models.filter {
            $0.provider == model.answers.awakeProvider && $0.isChatModel != false
        } ?? []
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            StepTitle("Intelligence", subtitle: "OS 1 detected a recommended setup. Accept it or configure every detail manually.")
            if let configured = model.modelMatrix?.configured {
                VStack(alignment: .leading, spacing: 3) {
                    Text("CURRENT SETUP")
                        .font(.system(size: 9, weight: .bold))
                        .kerning(1.1)
                        .foregroundStyle(Term.inkDim)
                    Text("\(configured.primaryProvider) / \(configured.primaryModel)")
                        .font(.system(size: 12, weight: .medium))
                    Text("This remains selected unless you choose the local recommendation below.")
                        .font(.system(size: 10.5)).foregroundStyle(Term.inkDim)
                }
            }
            if let error = model.catalogError {
                Text(error).foregroundStyle(.red)
                Button("Retry") { Task { await model.loadCatalog() } }
            } else if model.loading {
                ProgressView("Loading models…")
            } else {
                if let recommended = model.modelMatrix?.models.first(where: { $0.isRecommendedPrimary }) {
                    HStack(spacing: 12) {
                        Image(systemName: "sparkles")
                            .font(.system(size: 20))
                            .foregroundStyle(Term.accent)
                        VStack(alignment: .leading, spacing: 3) {
                            Text("RECOMMENDED LOCAL SETUP")
                                .font(.system(size: 9, weight: .bold))
                                .kerning(1.1)
                                .foregroundStyle(Term.accent)
                            Text(recommended.name)
                                .font(.system(size: 14, weight: .bold))
                            Text("\(recommended.providerLabel) · \(recommended.description)")
                                .font(.system(size: 10.5))
                                .foregroundStyle(Term.inkDim)
                                .lineLimit(2)
                            if let matrix = model.modelMatrix {
                                let sizeLabel = recommended.sizeGb.map {
                                    String(format: "%.1f GB", $0)
                                } ?? "small"
                                Text("Why: detected \(matrix.tierLabel) unified memory. This \(sizeLabel) model runs offline with enough headroom for Kokoro voice and Whisper listening.")
                                    .font(.system(size: 10.5, weight: .medium))
                                    .foregroundStyle(Term.ink)
                                    .lineLimit(2)
                            }
                        }
                        Spacer()
                        Button(model.useRecommended ? "Selected" : "Use this") {
                            model.applyRecommendation()
                            showManual = false
                        }
                        .disabled(model.useRecommended)
                    }
                    .padding(12)
                    .background(Term.accent.opacity(0.10))
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                    .overlay(RoundedRectangle(cornerRadius: 10)
                        .stroke(Term.accent.opacity(0.35), lineWidth: 1))
                }

                Button(showManual ? "Hide manual configuration" : "Configure manually") {
                    showManual.toggle()
                }
                .buttonStyle(.plain)
                .foregroundStyle(Term.accent)

                if showManual || !model.useRecommended {
                Picker("Provider", selection: Binding(
                    get: { model.answers.awakeProvider },
                    set: { model.selectProvider($0) })) {
                    Text("Choose a provider").tag("")
                    ForEach(model.modelMatrix?.providers ?? []) { entry in
                        Text(entry.name).tag(entry.id)
                    }
                }
                .pickerStyle(.menu)
                if let provider {
                    Text(provider.endpoint).font(.system(size: 12)).foregroundStyle(Term.inkDim)
                    if provider.requiresKey {
                        HStack {
                            SecureField("API key", text: $model.calibrationKey)
                            Button(model.isCalibrating ? "Saving…" : "Save key") {
                                Task { await model.calibrate(provider: provider, apiKey: model.calibrationKey) }
                            }.disabled(model.isCalibrating || model.calibrationKey.isEmpty)
                        }
                        if provider.status == "configured" || provider.status == "connected" {
                            Text("Credentials configured").foregroundStyle(.green)
                        }
                        if let error = model.calibrationError { Text(error).foregroundStyle(.red) }
                    }
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 8) {
                            ForEach(choices) { entry in
                                Button { model.selectModel(entry) } label: {
                                    HStack {
                                        Image(systemName: model.answers.awakeModel == entry.id ? "checkmark.circle.fill" : "circle")
                                        VStack(alignment: .leading, spacing: 3) {
                                            Text(entry.name).font(.system(size: 14, weight: .medium))
                                            Text(entry.id).font(.system(size: 11)).foregroundStyle(Term.inkDim)
                                        }
                                        Spacer()
                                        Text(entry.location).font(.system(size: 11))
                                    }
                                    .padding(12)
                                    .background(model.answers.awakeModel == entry.id ? Term.accent.opacity(0.2) : Color.white.opacity(0.04))
                                    .clipShape(RoundedRectangle(cornerRadius: 8))
                                }.buttonStyle(.plain)
                            }
                        }
                    }
                    HStack {
                        Text("Model ID").font(.system(size: 12))
                        TextField("Choose above or enter an exact model ID", text: $model.answers.awakeModel)
                    }
                    Text("Your selection is saved and loaded only after you confirm Start OS 1.")
                        .font(.system(size: 12)).foregroundStyle(Term.inkDim)
                }
                }
            }
            Spacer(minLength: 0)
        }
    }
}

private struct ProviderFilterPill: View {
    let title: String
    let isSelected: Bool
    let dotColor: Color
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Circle()
                    .fill(dotColor)
                    .frame(width: 7, height: 7)
                Text(title)
                    .font(.system(size: 11, weight: isSelected ? .bold : .medium))
                    .foregroundStyle(isSelected ? .white : Term.ink)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(isSelected ? Term.accent.opacity(0.3) : Term.panel)
            .clipShape(Capsule())
            .overlay(
                Capsule()
                    .stroke(isSelected ? Term.accent : Color.white.opacity(0.1), lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }
}

private struct ProviderPill: View {
    let provider: ModelProvider
    let isSelected: Bool
    let onSelect: () -> Void
    let onCalibrate: () -> Void

    var body: some View {
        Button(action: {
            if provider.status == "needs_key" {
                onCalibrate()
            } else {
                onSelect()
            }
        }) {
            HStack(spacing: 6) {
                Circle()
                    .fill(statusColor)
                    .frame(width: 7, height: 7)
                Text(provider.name)
                    .font(.system(size: 11, weight: isSelected ? .bold : .medium))
                    .foregroundStyle(isSelected ? .white : Term.ink)
                if provider.status == "needs_key" {
                    Text("CALIBRATE")
                        .font(.system(size: 8, weight: .heavy))
                        .padding(.horizontal, 5)
                        .padding(.vertical, 2)
                        .background(Color.yellow.opacity(0.2))
                        .foregroundStyle(Color.yellow)
                        .clipShape(RoundedRectangle(cornerRadius: 3))
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(isSelected ? Term.accent.opacity(0.3) : Term.panel)
            .clipShape(Capsule())
            .overlay(
                Capsule()
                    .stroke(isSelected ? Term.accent : (provider.status == "needs_key" ? Color.yellow.opacity(0.4) : Color.white.opacity(0.1)), lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }

    private var statusColor: Color {
        switch provider.status {
        case "connected", "available", "configured":
            return Color(red: 0.35, green: 0.95, blue: 0.70)
        case "needs_key":
            return Color.yellow
        default:
            return Color.gray.opacity(0.6)
        }
    }
}

private struct ModelSlotCard: View {
    let title: String
    let slotTag: String
    let selectedModel: DiscoveredModelEntry?
    let fallbackText: String
    let models: [DiscoveredModelEntry]
    let isInspecting: Bool
    let onSelectModel: (String) -> Void
    let onInspect: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(title)
                    .font(.system(size: 9, weight: .bold))
                    .kerning(1.2)
                    .foregroundStyle(Term.inkDim)
                Spacer()
                Button(action: onInspect) {
                    HStack(spacing: 4) {
                        Image(systemName: isInspecting ? "info.circle.fill" : "info.circle")
                        Text(isInspecting ? "Inspecting" : "Quick Info")
                    }
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(isInspecting ? Term.accent : Term.inkDim)
                }
                .buttonStyle(.plain)
            }

            HStack(alignment: .center, spacing: 10) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(selectedModel?.name ?? fallbackText)
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(Term.ink)
                        .lineLimit(1)
                    HStack(spacing: 6) {
                        Text(selectedModel?.providerLabel ?? "Unknown Provider")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(Term.accent)
                        if let size = selectedModel?.sizeGb {
                            Text("•  \(String(format: "%.1f GB", size))")
                                .font(Term.mono)
                                .font(.system(size: 10))
                                .foregroundStyle(Term.inkDim)
                        } else if let loc = selectedModel?.location, loc == "cloud" {
                            Text("•  Cloud")
                                .font(.system(size: 10))
                                .foregroundStyle(Term.inkDim)
                        }
                        if let ctx = selectedModel?.contextLength {
                            Text("•  \(formatContextLength(ctx))")
                                .font(.system(size: 10, weight: .medium))
                                .foregroundStyle(Term.inkDim)
                        }
                        if let speed = selectedModel?.speed {
                            Text("•  \(speed)")
                                .font(.system(size: 10))
                                .foregroundStyle(Term.inkDim)
                        }
                    }
                }
                Spacer()

                Menu {
                    let chatModels = models.filter { $0.role != "embedding" && ($0.isChatModel ?? true) }
                    let providerOrder: [(id: String, name: String)] = [
                        ("ollama-local", "Ollama (Local)"),
                        ("in-process", "Local GGUF / MLX"),
                        ("ollama-cloud", "Ollama Cloud"),
                        ("anthropic", "Anthropic"),
                        ("openai", "OpenAI"),
                        ("gemini", "Google Gemini"),
                        ("xai", "xAI Grok"),
                    ]

                    let distinctProviders = Set(chatModels.map(\.provider))
                    if distinctProviders.count == 1 {
                        ForEach(chatModels) { m in
                            Button(action: { onSelectModel(m.id) }) {
                                HStack {
                                    Text(m.name)
                                    if let sz = m.sizeGb {
                                        Text("(\(String(format: "%.1f GB", sz)))")
                                    }
                                    if let ctx = m.contextLength {
                                        Text("• \(formatContextLength(ctx))")
                                    }
                                    if m.id == selectedModel?.id {
                                        Image(systemName: "checkmark")
                                    }
                                }
                            }
                        }
                    } else {
                        ForEach(providerOrder, id: \.id) { prov in
                            let provModels = chatModels.filter { $0.provider == prov.id }
                            if !provModels.isEmpty {
                                Menu(prov.name) {
                                    ForEach(provModels) { m in
                                        Button(action: { onSelectModel(m.id) }) {
                                            HStack {
                                                Text(m.name)
                                                if let sz = m.sizeGb {
                                                    Text("(\(String(format: "%.1f GB", sz)))")
                                                }
                                                if let ctx = m.contextLength {
                                                    Text("• \(formatContextLength(ctx))")
                                                }
                                                if m.id == selectedModel?.id {
                                                    Image(systemName: "checkmark")
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        let knownIds = Set(providerOrder.map(\.id))
                        let otherProviders = Array(Set(chatModels.map(\.provider).filter { !knownIds.contains($0) })).sorted()
                        ForEach(otherProviders, id: \.self) { provId in
                            let provModels = chatModels.filter { $0.provider == provId }
                            if !provModels.isEmpty {
                                let label = provModels.first?.providerLabel ?? provId
                                Menu(label) {
                                    ForEach(provModels) { m in
                                        Button(action: { onSelectModel(m.id) }) {
                                            HStack {
                                                Text(m.name)
                                                if let sz = m.sizeGb {
                                                    Text("(\(String(format: "%.1f GB", sz)))")
                                                }
                                                if let ctx = m.contextLength {
                                                    Text("• \(formatContextLength(ctx))")
                                                }
                                                if m.id == selectedModel?.id {
                                                    Image(systemName: "checkmark")
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                } label: {
                    HStack(spacing: 4) {
                        Text("Select")
                            .font(.system(size: 11, weight: .bold))
                        Image(systemName: "chevron.up.chevron.down")
                            .font(.system(size: 8))
                    }
                    .foregroundStyle(.white)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background(Term.accent)
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                }
                .menuStyle(.borderlessButton)
            }
        }
        .padding(12)
        .background(Term.panel)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(isInspecting ? Term.accent.opacity(0.6) : Color.white.opacity(0.08), lineWidth: isInspecting ? 1.5 : 1)
        )
    }
}

private struct ModelMetadataCard: View {
    let slotLabel: String
    let model: DiscoveredModelEntry?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("NEURAL METADATA — \(slotLabel.uppercased())")
                    .font(.system(size: 9, weight: .bold))
                    .kerning(1.2)
                    .foregroundStyle(Term.accent)
                Spacer()
                if let loc = model?.location {
                    HStack(spacing: 4) {
                        Circle()
                            .fill(loc == "local" ? Color(red: 0.35, green: 0.95, blue: 0.70) : Color.blue)
                            .frame(width: 6, height: 6)
                        Text(loc == "local" ? "Local Host" : "Cloud Hosted")
                            .font(.system(size: 10, weight: .bold))
                            .foregroundStyle(loc == "local" ? Color(red: 0.35, green: 0.95, blue: 0.70) : Color.blue)
                    }
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(Color.white.opacity(0.05))
                    .clipShape(Capsule())
                }
            }

            if let m = model {
                HStack(spacing: 16) {
                    metaStat(label: "CONTEXT", value: formatContext(m.contextLength))
                    metaStat(label: "FOOTPRINT", value: formatSize(m.sizeGb, loc: m.location))
                    metaStat(label: "LATENCY TIER", value: m.speed)
                    metaStat(label: "ROLE", value: m.role.uppercased())
                }

                Text(m.description)
                    .font(.system(size: 11))
                    .foregroundStyle(Term.inkDim)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Text("Select a model slot above to inspect neural metadata, parameters, and benchmark characteristics.")
                    .font(.system(size: 11))
                    .foregroundStyle(Term.inkDim)
            }
        }
        .padding(12)
        .background(Term.panel.opacity(0.7))
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.06), lineWidth: 1))
    }

    private func metaStat(label: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.system(size: 8, weight: .bold))
                .kerning(1.0)
                .foregroundStyle(Term.inkDim)
            Text(value)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(Term.ink)
        }
    }

    private func formatContext(_ len: Int?) -> String {
        formatContextLength(len)
    }

    private func formatSize(_ sizeGb: Double?, loc: String) -> String {
        if let sizeGb, sizeGb > 0 {
            return String(format: "%.1f GB VRAM", sizeGb)
        }
        return loc == "cloud" ? "API Managed" : "Dynamic"
    }
}

private func formatContextLength(_ len: Int?) -> String {
    guard let len, len > 0 else { return "Dynamic" }
    if len >= 1_000_000 {
        let m = Double(len) / 1_000_000.0
        return m >= 1.0 ? String(format: "%.0fM tokens", m) : "1M tokens"
    } else if len >= 1_000 {
        if len == 200_000 { return "200K tokens" }
        if len == 128_000 { return "128K tokens" }
        let k = (len % 1024 == 0) ? (len / 1024) : (len / 1000)
        return "\(k)K tokens"
    }
    return "\(len) tokens"
}

private struct ConfiguredModelRow: View {
    let roleTag: String
    let title: String
    let subtitle: String
    let icon: String
    let models: [DiscoveredModelEntry]
    let currentValue: String
    let allowNone: Bool
    let onSelect: (String) -> Void

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 13))
                .foregroundStyle(Term.accent)
                .frame(width: 18)

            VStack(alignment: .leading, spacing: 2) {
                Text(roleTag)
                    .font(.system(size: 8, weight: .heavy))
                    .kerning(1.0)
                    .foregroundStyle(Term.inkDim)
                Text(title)
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Term.ink)
                    .lineLimit(1)
                Text(subtitle)
                    .font(.system(size: 9))
                    .foregroundStyle(Term.inkDim.opacity(0.8))
                    .lineLimit(1)
            }

            Spacer()

            Menu {
                if allowNone {
                    Button("None (Disable Failover)") {
                        onSelect("")
                    }
                    Divider()
                }

                let chatModels = models.filter { $0.role != "embedding" && ($0.isChatModel ?? true) }
                let providerOrder: [(id: String, name: String)] = [
                    ("ollama-local", "Ollama (Local)"),
                    ("ollama-cloud", "Ollama Cloud"),
                    ("in-process", "Local GGUF (In-Process)"),
                    ("anthropic", "Anthropic Claude"),
                    ("openai", "OpenAI"),
                    ("gemini", "Google Gemini"),
                    ("xai", "xAI Grok"),
                ]

                ForEach(providerOrder, id: \.id) { prov in
                    let provModels = chatModels.filter { $0.provider == prov.id }
                    if !provModels.isEmpty {
                        Menu(prov.name) {
                            ForEach(provModels) { m in
                                Button(action: { onSelect(m.id) }) {
                                    HStack {
                                        Text(m.name)
                                        if let sz = m.sizeGb {
                                            Text("(\(String(format: "%.1f GB", sz)))")
                                        }
                                        if let ctx = m.contextLength {
                                            Text("• \(formatContextLength(ctx))")
                                        }
                                        if m.id == currentValue {
                                            Image(systemName: "checkmark")
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                let knownIds = Set(providerOrder.map(\.id))
                let otherProviders = Array(Set(chatModels.map(\.provider).filter { !knownIds.contains($0) })).sorted()
                ForEach(otherProviders, id: \.self) { provId in
                    let provModels = chatModels.filter { $0.provider == provId }
                    if !provModels.isEmpty {
                        let label = provModels.first?.providerLabel ?? provId
                        Menu(label) {
                            ForEach(provModels) { m in
                                Button(action: { onSelect(m.id) }) {
                                    HStack {
                                        Text(m.name)
                                        if let sz = m.sizeGb {
                                            Text("(\(String(format: "%.1f GB", sz)))")
                                        }
                                        if let ctx = m.contextLength {
                                            Text("• \(formatContextLength(ctx))")
                                        }
                                        if m.id == currentValue {
                                            Image(systemName: "checkmark")
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            } label: {
                HStack(spacing: 4) {
                    Text("Change")
                        .font(.system(size: 10, weight: .bold))
                    Image(systemName: "chevron.up.chevron.down")
                        .font(.system(size: 8))
                }
                .foregroundStyle(Term.accent)
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(Term.accent.opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: 5))
                .overlay(RoundedRectangle(cornerRadius: 5).stroke(Term.accent.opacity(0.3), lineWidth: 1))
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(Color.white.opacity(0.03))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

private struct ConfiguredRow: View {
    let roleTag: String
    let title: String
    let subtitle: String
    let icon: String
    let options: [(String, String)]
    let currentValue: String
    let onSelect: (String) -> Void

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 13))
                .foregroundStyle(Term.accent)
                .frame(width: 18)

            VStack(alignment: .leading, spacing: 2) {
                Text(roleTag)
                    .font(.system(size: 8, weight: .heavy))
                    .kerning(1.0)
                    .foregroundStyle(Term.inkDim)
                Text(title)
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Term.ink)
                    .lineLimit(1)
                Text(subtitle)
                    .font(.system(size: 9))
                    .foregroundStyle(Term.inkDim.opacity(0.8))
                    .lineLimit(1)
            }

            Spacer()

            Menu {
                ForEach(options, id: \.0) { opt in
                    Button(action: { onSelect(opt.0) }) {
                        HStack {
                            Text(opt.1)
                            if opt.0 == currentValue {
                                Image(systemName: "checkmark")
                            }
                        }
                    }
                }
            } label: {
                HStack(spacing: 4) {
                    Text("Change")
                        .font(.system(size: 10, weight: .bold))
                    Image(systemName: "chevron.up.chevron.down")
                        .font(.system(size: 8))
                }
                .foregroundStyle(Term.accent)
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(Term.accent.opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: 5))
                .overlay(RoundedRectangle(cornerRadius: 5).stroke(Term.accent.opacity(0.3), lineWidth: 1))
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(Color.white.opacity(0.03))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

private struct ConfiguredMiniCard: View {
    let roleTag: String
    let name: String
    let subtitle: String
    let icon: String

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.system(size: 12))
                .foregroundStyle(Color(red: 0.35, green: 0.95, blue: 0.70))

            VStack(alignment: .leading, spacing: 1) {
                Text(roleTag)
                    .font(.system(size: 8, weight: .heavy))
                    .kerning(0.8)
                    .foregroundStyle(Term.inkDim)
                Text(name)
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Term.ink)
                    .lineLimit(1)
                Text(subtitle)
                    .font(.system(size: 9))
                    .foregroundStyle(Term.inkDim.opacity(0.8))
            }
            Spacer()
            Circle()
                .fill(Color(red: 0.35, green: 0.95, blue: 0.70))
                .frame(width: 6, height: 6)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.white.opacity(0.03))
        .clipShape(RoundedRectangle(cornerRadius: 8))
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
                      subtitle: "Start the selected model, verify it responds, then begin your OS 1 initiation.")
            VStack(spacing: 0) {
                row("Instance", model.modelMatrix?.configured?.instanceName ?? model.agent.status?.instance ?? instanceIdPreview)
                row("Name", model.answers.displayName)
                row("Character", model.selectedCharacter?.name ?? model.answers.characterId)
                row("Voice", model.answers.voiceProfile)
                row("Posture", model.answers.interactionPosture)
                row("Provider", model.answers.awakeProvider)
                row("Model", model.answers.awakeModel)
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

    /// Client-side preview ONLY — the real slug is computed server-side
    /// (``setup_wizard._slug``) at write time; this mirrors that logic
    /// (lowercase, non ``[a-z0-9_-]`` runs → ``-``, trim ``-``/``_``) just
    /// for the review screen so the folder name isn't a surprise.
    private var instanceIdPreview: String {
        let pin = model.answers.pinnedName.trimmingCharacters(in: .whitespaces)
        let source = pin.isEmpty ? model.answers.displayName : pin
        let lowered = source.lowercased()
        let slug = lowered.map { c -> Character in
            (c.isLetter && c.isASCII) || c.isNumber || c == "_" || c == "-"
                ? c : "-"
        }
        var result = String(slug)
        while result.hasPrefix("-") || result.hasPrefix("_") { result.removeFirst() }
        while result.hasSuffix("-") || result.hasSuffix("_") { result.removeLast() }
        return result.isEmpty ? "agent" : result
    }

    private func recommended(
        _ path: KeyPath<SetupDefaults, SetupDefaults.ModelPick>) -> String {
        guard let d = model.defaults else { return "recommended" }
        return d[keyPath: path].displayName + "  (recommended)"
    }

    private func row(_ label: String, _ value: String,
                     dim: Bool = false, last: Bool = false) -> some View {
        VStack(spacing: 0) {
            HStack {
                Text(label.uppercased())
                    .font(.system(size: 10, weight: .bold))
                    .kerning(1.2)
                    .foregroundStyle(Term.inkDim)
                    .frame(width: 130, alignment: .leading)
                Text(value)
                    .font(.system(size: dim ? 12 : 13, weight: .medium))
                    .foregroundStyle(dim ? Term.inkDim : Term.ink)
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
                Text("Starting your OS…")
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
