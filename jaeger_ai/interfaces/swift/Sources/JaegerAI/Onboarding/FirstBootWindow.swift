//
//  FirstBootWindow.swift
//  JaegerAI / Onboarding
//
//  The OS 1 welcome, presented as a focused centered window.
//
//  Deliberately NOT a menu-bar popover: this is the one moment the product
//  asks for undivided attention, and a popover dismisses when the operator
//  clicks anywhere else — which would abandon the sequence mid-question.
//  The window is borderless, centered, and stays until first boot finishes
//  or the operator explicitly defers it.
//
//  Every word rendered here comes from the backend
//  (`first_boot_script.py`). Nothing in this file contains product copy —
//  if the wording lives in two places it will drift, and the sequence is a
//  product invariant.
//

import AppKit
import SwiftUI

@MainActor
final class FirstBootWindowController {

    private static var window: NSWindow?

    /// Present the welcome. Idempotent — a second call focuses the window
    /// already on screen rather than stacking a duplicate, so a double
    /// launch or a re-evaluation cannot show two welcomes.
    static func show(gate: FirstBootGate, turn: FirstBootGate.Turn) {
        if let existing = window {
            existing.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let view = FirstBootView(gate: gate, firstTurn: turn) { dismiss() }
        let hosting = NSHostingController(rootView: view)
        // SwiftUI content covers the window edge-to-edge, and a plain
        // hosting view reports itself as non-movable-background — the
        // NSWindow flags below were dead without a hosting-side contract.
        // A hosting view whose hit test reaches the chrome lets
        // isMovableByWindowBackground do its documented job: drag anywhere
        // that is not a control moves the welcome.
        hosting.sizingOptions = []

        let panel = NSWindow(contentViewController: hosting)
        panel.title = "OS 1"
        panel.styleMask = [.titled, .fullSizeContentView]
        panel.titlebarAppearsTransparent = true
        panel.titleVisibility = .hidden
        panel.isMovableByWindowBackground = true
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.setContentSize(NSSize(width: 840, height: 720))
        panel.center()
        panel.isReleasedWhenClosed = false
        // No close button: the sequence ends by completing or by the
        // operator choosing "Not now", both of which record state. A window
        // chrome close would leave first boot half-answered with no record
        // of why.
        panel.standardWindowButton(.closeButton)?.isHidden = true
        panel.standardWindowButton(.miniaturizeButton)?.isHidden = true
        panel.standardWindowButton(.zoomButton)?.isHidden = true

        window = panel
        panel.makeKeyAndOrderFront(nil)
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }

    static func dismiss() {
        window?.orderOut(nil)
        window = nil
    }

    static var isPresented: Bool { window != nil }
}


/// The welcome itself. One question at a time, exactly as the backend
/// state machine serves it.
struct FirstBootView: View {

    @ObservedObject var gate: FirstBootGate
    let firstTurn: FirstBootGate.Turn
    let onFinish: () -> Void

    @State private var turn: FirstBootGate.Turn
    @State private var reply: String = ""
    @State private var busy = false
    @State private var errorText: String?
    @State private var spoken = false
    @State private var personaArrived = false

    // Hybrid: live hardware bench stream + character fork
    @State private var benchId: String?
    @State private var benchStatus: String = "idle"
    @State private var benchCurrent: String = ""
    @State private var benchProgress: Double = 0
    @State private var benchEta: Int = 0
    @State private var benchLog: [(name: String, detail: String, value: String, ok: Bool)] = []
    @State private var benchTier: String = ""
    @State private var characters: [OnboardingCharacter] = []
    @State private var selectedCharacterId: String?
    @State private var benchTask: Task<Void, Never>?
    @State private var showManual = false
    @State private var narrationTask: Task<Void, Never>?
    @StateObject private var answerRecorder = VoiceRecorder()
    /// Monitor-only mic for barge-in during installer narration. Separate
    /// from ``answerRecorder`` on purpose: this one scores frames and drops
    /// them (nothing retained), while the answer recorder captures for
    /// transcription. One tap cannot be both without retaining audio
    /// during speech the operator did not ask to record.
    @StateObject private var bargeInRecorder = VoiceRecorder()
    @State private var transcribing = false
    @State private var requestingMicrophone = false
    @State private var microphoneAvailable = VoiceRecorder.hasAudioInput
    @State private var recordedEnergyVariance: Float?
    @State private var automaticListening = false
    @State private var began = false

    private let tts = TTSManager.shared
    private let ambient = AmbientCoordinator.shared

    /// Watches Probe 3 and cuts in once enough signal is captured.
    @State private var truncationWatch: Task<Void, Never>?

    /// Mirrors the backend thresholds in first_boot_script.py. Duplicated
    /// deliberately: the client must decide locally and instantly, and a
    /// round trip per second to ask "enough yet?" would make the cut land
    /// late and unevenly.
    private static let truncateAfterSeconds: Double = 6.0

    init(gate: FirstBootGate, firstTurn: FirstBootGate.Turn, onFinish: @escaping () -> Void) {
        self.gate = gate
        self.firstTurn = firstTurn
        self.onFinish = onFinish
        _turn = State(initialValue: firstTurn)
        let status = gate.status
        _began = State(initialValue: status != "AWAITING_BENCH"
                       && status != "NOT_STARTED"
                       && status != "unknown")
    }

    /// Which question the current turn is asking, in the backend's terms.
    private var questionKey: String {
        switch gate.status {
        case "AWAITING_BENCH", "DISCOVERING_HOST": return "bench"
        case "AWAITING_CHARACTER": return "character"
        case "AWAITING_SOCIAL":    return "social"
        case "AWAITING_HESITANCE": return "hesitance"
        case "AWAITING_Q2":        return "q2"
        case "AWAITING_PERMISSIONS": return "permissions"
        case "AWAITING_INTEGRATIONS": return "integrations"
        case "AWAITING_KNOWLEDGE_APPROVAL": return "knowledge"
        case "DISCOVERING_SERVICES",
             "DISCOVERING_PROVIDERS",
             "CERTIFYING_PROVIDERS",
             "CONFIGURING_RUNTIME",
             "STARTING_RESIDENT",
             "VALIDATING_CORE",
             "VALIDATING_TOOLS",
             "VALIDATING_MEMORY",
             "VALIDATING_BACKGROUND",
             "RESTARTING_FOR_PERSISTENCE_TEST",
             "VERIFYING_PERSISTENCE",
             "INITIAL_INDEXING":
            return "tick"
        default:                   return "voice"
        }
    }

    private var isBenchTurn: Bool {
        gate.status == "AWAITING_BENCH" || gate.status == "DISCOVERING_HOST" || questionKey == "bench"
    }
    private var isCommissioningTurn: Bool { questionKey == "tick" }
    private var isCharacterTurn: Bool { gate.status == "AWAITING_CHARACTER" }
    private var isVoiceTurn: Bool { gate.status == "AWAITING_VOICE" }
    private var showWelcome: Bool { isBenchTurn && !began }

    /// The system can speak briskly without beginning a personal question
    /// the instant the next page appears. The beat belongs before the prompt,
    /// while the voice itself stays responsive rather than slow.
    private var narrationLeadIn: Duration {
        switch gate.status {
        case "AWAITING_SOCIAL", "AWAITING_HESITANCE", "AWAITING_VOICE", "AWAITING_Q2":
            return .milliseconds(650)
        case "AWAITING_CHARACTER":
            return .milliseconds(400)
        default:
            return .zero
        }
    }

    private var visibleLines: [String] {
        guard turn.isPersonaHandoff else { return turn.lines }
        return personaArrived ? Array(turn.lines.dropFirst()) : Array(turn.lines.prefix(1))
    }

    private var stage: (index: Int, title: String) {
        if turn.isPersonaHandoff { return (4, "First conversation") }
        switch gate.status {
        case "AWAITING_CHARACTER": return (1, "Your companion")
        case "AWAITING_SOCIAL", "AWAITING_HESITANCE": return (2, "Getting acquainted")
        case "AWAITING_VOICE", "AWAITING_Q2": return (3, "Voice & personality")
        case "AWAITING_PERMISSIONS", "AWAITING_INTEGRATIONS", "AWAITING_KNOWLEDGE_APPROVAL":
            return (3, "Getting ready")
        case "DISCOVERING_SERVICES",
             "DISCOVERING_PROVIDERS",
             "CERTIFYING_PROVIDERS",
             "CONFIGURING_RUNTIME",
             "STARTING_RESIDENT",
             "VALIDATING_CORE",
             "VALIDATING_TOOLS",
             "VALIDATING_MEMORY",
             "VALIDATING_BACKGROUND",
             "RESTARTING_FOR_PERSISTENCE_TEST",
             "VERIFYING_PERSISTENCE",
             "INITIAL_INDEXING":
            return (3, "Setting up your AI")
        default: return (0, "Intelligence")
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 22) {
            HStack(spacing: 12) {
                JaegerMechIcon(size: 22)
                Text("JENKINS ROBOTICS · JAEGER AI · OS 1 SETUP")
                    .font(.system(size: 11, weight: .semibold))
                    .kerning(2.2)
                    .foregroundStyle(Term.inkDim)
                Spacer()
            }
            HStack(spacing: 8) {
                ForEach(0..<5) { index in
                    Capsule()
                        .fill(index == stage.index ? Term.accent :
                              index < stage.index ? Term.accent.opacity(0.45) : Color.white.opacity(0.14))
                        .frame(width: index == stage.index ? 26 : 14, height: 4)
                }
                Spacer()
                Text(stage.title.uppercased())
                    .font(.system(size: 10, weight: .bold))
                    .kerning(1.6)
                    .foregroundStyle(Term.inkDim)
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Step \(stage.index + 1) of 5: \(stage.title)")
        }
        .padding(EdgeInsets(top: 28, leading: 30, bottom: 20, trailing: 30))
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            ScrollViewReader { scrollProxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        if showWelcome {
                            OS1WelcomeHero()
                                .frame(maxWidth: .infinity)
                                .id("stage-top")
                        } else {
                        Text(stage.title)
                            .font(.system(size: 32, weight: .bold))
                            .foregroundStyle(.white)
                            .id("stage-top")

            ForEach(Array(visibleLines.enumerated()), id: \.offset) { _, line in
                narrationLine(line)
            }

            if isBenchTurn {
                architectureRow
                benchPanel
                if benchStatus == "done" { modelChoicePanel }
                if let failure = gate.setupError { Text(failure).foregroundStyle(.red) }
                if !busy && benchStatus != "done" {
                    Button("Retry system check") { benchTask = nil; startBenchIfNeeded() }
                }
            }

            if isCharacterTurn {
                characterPanel
            }
            if let failure = gate.setupError, !isBenchTurn {
                Text(failure).foregroundStyle(.red)
                modelChoicePanel
                Button("Retry selected model") {
                    Task { @MainActor in
                        busy = true
                        defer { busy = false }
                        if await gate.startSelectedModel() {
                            spoken = false
                            speakCurrentTurn()
                        }
                    }
                }.disabled(busy)
            }

            if isVoiceTurn {
                voiceCards
            } else if turn.awaitsReply && !turn.isPersonaHandoff && !isCharacterTurn && !isBenchTurn {
                answerInputSection
            }

            if turn.isPersonaHandoff, let record = gate.personaNameRecord {
                namingPanel(record)
            }

            if let errorText {
                Text(errorText)
                    .font(.system(size: 13))
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }

                        } // end else !showWelcome

                    }
                    .padding(.horizontal, 30)
                    .padding(.bottom, 20)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .onChange(of: stage.index) { _, _ in
                    scrollProxy.scrollTo("stage-top", anchor: .top)
                }
                .onChange(of: benchStatus) { _, status in
                    if status == "done" {
                        scrollProxy.scrollTo("stage-top", anchor: .top)
                    }
                }
            }

            HStack {
                Button("Not now") { onFinish() }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
                Spacer()
                if busy { ProgressView().controlSize(.small) }
                if showWelcome {
                    Button("Begin Setup") { beginSetup() }
                        .buttonStyle(FirstBootActionStyle(primary: true))
                        .keyboardShortcut(.defaultAction)
                        .disabled(busy)
                } else if isBenchTurn {
                    Button(busy ? "Preparing…" : "Use this setup") { confirmModel() }
                        .buttonStyle(FirstBootActionStyle(primary: true))
                        .disabled(busy || benchStatus != "done" || gate.selectedModel.isEmpty)
                } else if isCharacterTurn {
                    Button(characterContinueLabel) { confirmCharacter() }
                        .buttonStyle(FirstBootActionStyle(primary: true))
                        .keyboardShortcut(.defaultAction)
                        .disabled(busy || selectedCharacterId == nil)
                } else if isCommissioningTurn {
                    ProgressView().controlSize(.small)
                } else if !isCharacterTurn && !isVoiceTurn {
                    Button(turn.isPersonaHandoff ? "Continue" : "Send") { submit() }
                        .buttonStyle(FirstBootActionStyle(primary: true))
                        .keyboardShortcut(.defaultAction)
                        .disabled(busy || transcribing || answerRecorder.isRecording || gate.setupError != nil || (turn.isPersonaHandoff && !personaArrived) || (!turn.isPersonaHandoff && reply.trimmingCharacters(
                            in: .whitespacesAndNewlines).isEmpty))
                }
            }
            .padding(EdgeInsets(top: 16, leading: 30, bottom: 24, trailing: 30))
        }
        .frame(minWidth: 720, minHeight: 620)
        .background {
            ZStack {
                Term.canvas
                LinearGradient(colors: [Term.accent.opacity(0.14), .clear, .clear],
                               startPoint: .topLeading, endPoint: .bottomTrailing)
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 18))
        .overlay(RoundedRectangle(cornerRadius: 18).stroke(Color.white.opacity(0.08)))
        .foregroundStyle(Term.ink)
        .tint(Term.accent)
        .preferredColorScheme(.dark)
        .buttonStyle(FirstBootActionStyle())
        .onAppear {
            // The welcome page speaks: the greeting is the product's first
            // words, and voice must not wait for a click. The bench itself
            // still waits for Begin Setup — that is the one deliberate
            // beat the operator owns.
            Task { await gate.warmUpSpeech() }
            speakCurrentTurn()
            // Only a resumed walk (began) continues the bench; on the
            // welcome page the bench waits for Begin Setup — that beat
            // belongs to the operator, and auto-starting here cuts the
            // greeting off mid-sentence via the auto-advance.
            if isBenchTurn && began { startBenchIfNeeded() }
            if isCharacterTurn { loadCharactersIfNeeded() }
            if isCommissioningTurn { pollCommissioning() }
        }
        .onChange(of: gate.status) { _, newStatus in
            if newStatus == "AWAITING_BENCH" && began { startBenchIfNeeded() }
            if newStatus == "AWAITING_CHARACTER" { loadCharactersIfNeeded() }
            if questionKey == "tick" { pollCommissioning() }
        }
        .onDisappear {
            truncationWatch?.cancel()
            benchTask?.cancel()
            narrationTask?.cancel()
            answerRecorder.stopRecording()
            answerRecorder.onSpeechOnset = nil
            answerRecorder.onSpeechEnded = nil
            stopBargeInMonitoring()
            STTManager.shared.cancel()
            tts.stop()
            tts.enterVoiceStage(.persona)
        }
    }

    private func beginSetup() {
        began = true
        speakCurrentTurn()
        startBenchIfNeeded()
    }

    private var architectureRow: some View {
        HStack(alignment: .top, spacing: 12) {
            ArchitecturePillarCard(
                badge: "CONTINUOUS PRESENCE",
                icon: "waveform.circle.fill",
                title: "What is the Assistant?",
                description: "An integrated system on your Mac — memory across restarts, natural voice, and real work from the menu bar or ⌥Space.",
                compact: true
            )
            ArchitecturePillarCard(
                badge: "DUAL-STAGE COGNITION",
                icon: "bolt.horizontal.circle.fill",
                title: "How It Works",
                description: "Awake: conversation and tools. Asleep: reflection, relationship graph, and memory indexing in the background.",
                compact: true
            )
            ArchitecturePillarCard(
                badge: "MODEL FREEDOM",
                icon: "cpu.fill",
                title: "Why It's Different",
                description: "Session, voice, and tools stay on this Mac. Run fully offline, or plug in a frontier cloud model for deep reasoning.",
                compact: true
            )
        }
    }

    /// One narration line. The first line of a multi-line turn is a
    /// quiet lead-in; the rest is the main voice of the turn.
    private func narrationLine(_ line: String) -> some View {
        let isLead = line == turn.lines.first && turn.lines.count > 1
        return Text(line)
            .font(isLead ? Font.system(size: 15, weight: .regular)
                         : Font.system(size: 18, weight: .medium))
            .foregroundStyle(isLead ? Color.secondary : Color.primary)
            .fixedSize(horizontal: false, vertical: true)
    }

    /// The answer-input section, extracted from ``body`` so the overall
    /// expression stays inside the type-checker's budget.
    @ViewBuilder
    private var answerInputSection: some View {
        TextField("", text: $reply, prompt: Text("Your answer"))
            .textFieldStyle(.roundedBorder)
            .font(.system(size: 15))
            .onSubmit { submit() }
            .disabled(busy)
        Button(answerRecorder.isRecording ? "Finish recording" : "Speak your answer") {
            toggleAnswerRecording()
        }.disabled(busy || transcribing || requestingMicrophone)
        if answerRecorder.isRecording {
            HStack(spacing: 10) {
                Circle()
                    .fill(Color.red)
                    .frame(width: 8, height: 8)
                Text("Listening — speak naturally, then press Finish recording")
                    .font(.system(size: 13, weight: .medium))
                ProgressView(value: Double(answerRecorder.levelMeter))
                    .progressViewStyle(.linear)
                    .frame(maxWidth: 220)
            }
            .foregroundStyle(.secondary)
        }
        if transcribing { ProgressView("Transcribing…") }
        if requestingMicrophone { ProgressView("Requesting microphone access…") }
        if !microphoneAvailable {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Image(systemName: "mic.slash.fill")
                    .foregroundStyle(.orange)
                Text("No microphone is connected. Connect a USB, Bluetooth, or Continuity microphone, then try again.")
                    .font(.system(size: 13))
                    .foregroundStyle(.secondary)
                Spacer()
                Button("Check again") {
                    microphoneAvailable = VoiceRecorder.hasAudioInput
                }
            }
            .padding(14)
            .background(RoundedRectangle(cornerRadius: 10).fill(Term.panel))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.orange.opacity(0.35)))
        }
    }

    private var voiceCards: some View {
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
                    selected: reply.lowercased().contains("female")
                ) { submitVoice("female") }
                OS1OptionCard(
                    title: "Male Voice",
                    subtitle: "Even-keeled, grounded, calm delivery\n(Daniel / Kokoro am_michael)",
                    icon: "waveform.circle",
                    selected: reply.lowercased().contains("male") && !reply.lowercased().contains("female")
                ) { submitVoice("male") }
            }
        }
    }

    private func submitVoice(_ profile: String) {
        reply = profile
        submit()
    }

    private var benchPanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            ProgressView(value: benchProgress)
                .progressViewStyle(.linear)
            HStack {
                Text(benchCurrent.isEmpty ? "Starting hardware bench…" : benchCurrent)
                    .font(.system(size: 13, weight: .medium))
                Spacer()
                if benchEta > 0 {
                    Text("ETA ~\(benchEta)s")
                        .font(.system(size: 12).monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }
            if !benchTier.isEmpty {
                Text(benchTier)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.secondary)
            }
            ForEach(Array(benchLog.enumerated()), id: \.offset) { _, row in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(row.ok ? "✓" : "!")
                        .foregroundStyle(row.ok ? .green : .orange)
                        .font(.system(size: 12, weight: .bold))
                    Text(row.detail)
                        .font(.system(size: 12))
                    Spacer()
                    Text(row.value)
                        .font(.system(size: 12).monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(18)
        .background(RoundedRectangle(cornerRadius: 12).fill(Term.panel))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.white.opacity(0.08)))
    }

    private var characterPanel: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Choose a ready-made character, or select OS 1 Assistant for a custom calibration")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(.secondary)
            LazyVGrid(
                columns: Array(repeating: GridItem(.flexible(), spacing: 14), count: 4),
                spacing: 14
            ) {
                ForEach(characters) { character in
                    CharacterCard(
                        character: character,
                        selected: selectedCharacterId == character.id
                    ) {
                        selectedCharacterId = character.id
                    }
                    .disabled(busy)
                }
            }
            if let selectedCharacter {
                CharacterProfilePreview(character: selectedCharacter)
            }
        }
    }

    private var selectedCharacter: OnboardingCharacter? {
        guard let selectedCharacterId else { return nil }
        return characters.first { $0.id == selectedCharacterId }
    }

    private var characterContinueLabel: String {
        guard let selectedCharacter else { return "Choose a character" }
        return selectedCharacter.id == "assistant"
            ? "Calibrate my Assistant"
            : "Start as \(selectedCharacter.name)"
    }

    private func confirmCharacter() {
        guard let selectedCharacter else { return }
        pickCharacter(
            path: selectedCharacter.id == "assistant" ? "custom" : "preset",
            id: selectedCharacter.id
        )
    }

    private func namingPanel(_ record: [String: Any]) -> some View {
        let name = record["name"] as? String ?? ""
        let reason = record["reason"] as? String ?? ""
        let source = record["reason_source"] as? String ?? "corpus"
        return VStack(alignment: .leading, spacing: 6) {
            Text("Self-naming")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(.secondary)
            if !name.isEmpty {
                Text(name)
                    .font(.system(size: 18, weight: .semibold))
            }
            if !reason.isEmpty {
                Text(reason)
                    .font(.system(size: 13))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text(source == "model" ? "Reason: live model" : "Reason: name corpus (model soft-failed or offline)")
                .font(.system(size: 11))
                .foregroundStyle(.tertiary)
        }
        .padding(18)
        .background(RoundedRectangle(cornerRadius: 12).fill(Term.panel))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.white.opacity(0.08)))
    }


    private func startBenchIfNeeded() {
        guard benchTask == nil else { return }
        benchTask = Task { @MainActor in
            busy = true
            defer { busy = false }
            await gate.loadModelChoices()
            guard let started = await gate.startHardwareBench() else {
                errorText = "Hardware bench could not start."
                return
            }
            benchId = started["id"] as? String
            applyBenchPayload(started)
            let deadline = ContinuousClock.now + .seconds(45)
            var autoAdvanced = false
            while !Task.isCancelled && ContinuousClock.now < deadline {
                try? await Task.sleep(nanoseconds: 400_000_000)
                guard let snap = await gate.hardwareBenchStatus(id: benchId) else { continue }
                applyBenchPayload(snap)
                let status = snap["status"] as? String ?? ""
                if status == "done" && !autoAdvanced {
                    // The installer moves the operator forward himself —
                    // but never over himself. The greeting + bench
                    // narration outlasts an 11s bench, so hold the advance
                    // until the voice finishes; cutting the welcome to swap
                    // panels is how the greeting dies unheard.
                    autoAdvanced = true
                    while !Task.isCancelled, tts.isSpeaking {
                        try? await Task.sleep(nanoseconds: 250_000_000)
                    }
                    try? await Task.sleep(nanoseconds: 400_000_000)
                    await advanceAfterBench()
                    return
                }
                if status == "error" {
                    errorText = snap["error"] as? String ?? "Hardware bench failed"
                    return
                }
            }
            if !Task.isCancelled { errorText = "System check timed out. Please retry." }
        }
    }

    private var modelChoicePanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Recommended for this Mac")
                .font(.caption.weight(.semibold))
                .foregroundStyle(Term.accent)
                .textCase(.uppercase)
            Text(gate.selectedModel == gate.bundledModelPath
                 ? "\(bundledModelName) · bundled and offline"
                 : gate.selectedModel)
                .font(.headline)
            Text("Actions will ask for confirmation. Larger models may need a download.")
                .font(.caption).foregroundStyle(.secondary)
            if !gate.bundledModelPath.isEmpty && gate.selectedModel != gate.bundledModelPath {
                Divider().padding(.vertical, 4)
                Text("Offline fallback")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Button("Switch to \(bundledModelName)") {
                    gate.selectedProvider = "in-process"
                    gate.selectedModel = gate.bundledModelPath
                }
            }
            DisclosureGroup("Choose another model", isExpanded: $showManual) {
                Picker("Provider", selection: Binding(get: { gate.selectedProvider }, set: {
                    gate.selectedProvider = $0
                    gate.selectedModel = ""
                    gate.providerKey = ""
                })) {
                    ForEach(gate.modelMatrix?.providers ?? []) { Text($0.name).tag($0.id) }
                }
                Picker("Model", selection: $gate.selectedModel) {
                    Text("Enter a model below").tag("")
                    ForEach((gate.modelMatrix?.models ?? []).filter {
                        $0.provider == gate.selectedProvider && $0.isChatModel != false
                    }) { Text($0.name).tag($0.id) }
                }
                TextField("Exact model ID or local path", text: $gate.selectedModel)
                if gate.modelMatrix?.providers.first(where: { $0.id == gate.selectedProvider })?.requiresKey == true {
                    SecureField("API key (leave blank to use saved credentials)", text: $gate.providerKey)
                }
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(Term.accent.opacity(0.08)))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Term.accent.opacity(0.45)))
    }

    private var bundledModelName: String {
        let path = gate.bundledModelPath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !path.isEmpty else { return "bundled model" }
        let name = URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent
        return name.isEmpty ? "bundled model" : name
    }

    private func pollCommissioning() {
        Task { @MainActor in
            guard isCommissioningTurn else { return }
            busy = true
            defer { busy = false }
            for _ in 0..<40 {
                _ = await gate.submit(question: "tick", reply: "ok")
                switch await gate.evaluate() {
                case .onboard(let next):
                    turn = next
                    if next.awaitsReply || next.isPersonaHandoff {
                        spoken = false
                        speakCurrentTurn()
                        return
                    }
                case .proceed:
                    onFinish()
                    return
                case .unavailable:
                    return
                }
                try? await Task.sleep(nanoseconds: 400_000_000)
            }
        }
    }

    /// Manual "Use this setup" tap and the bench auto-advance share one
    /// path, so the button can never drift from what the voice does.
    private func confirmModel() {
        Task { @MainActor in
            await advanceAfterBench()
        }
    }

    private func advanceAfterBench() async {
        busy = true
        errorText = nil
        defer { busy = false }
        guard await gate.startSelectedModel() else { return }
        switch await gate.completeBench(benchId: benchId) {
        case .success(let next):
            guard let next else { return }
            turn = next
            spoken = false
            speakCurrentTurn()
            loadCharactersIfNeeded()
        case .failure(let failure): errorText = failure.message
        }
    }

    private func applyBenchPayload(_ snap: [String: Any]) {
        benchStatus = snap["status"] as? String ?? benchStatus
        benchCurrent = snap["current"] as? String ?? benchCurrent
        if let p = snap["progress"] as? Double { benchProgress = p }
        else if let p = snap["progress"] as? NSNumber { benchProgress = p.doubleValue }
        if let eta = snap["eta_s"] as? Int { benchEta = eta }
        else if let eta = snap["eta_s"] as? NSNumber { benchEta = eta.intValue }
        if let rec = snap["recommendation"] as? [String: Any] {
            let tier = rec["tier_label"] as? String ?? ""
            var mem = ""
            if let n = rec["host_memory_gb"] as? Double { mem = String(format: "%.0f", n) }
            else if let n = rec["host_memory_gb"] as? NSNumber { mem = String(format: "%.0f", n.doubleValue) }
            let awake = (rec["awake"] as? [String: Any])?["display_name"] as? String ?? ""
            benchTier = [tier, mem.isEmpty ? "" : "\(mem) GB", awake]
                .filter { !$0.isEmpty }.joined(separator: " · ")
        }
        if let log = snap["log"] as? [[String: Any]] {
            benchLog = log.map { row in
                (
                    name: row["name"] as? String ?? "",
                    detail: row["detail"] as? String ?? "",
                    value: row["value"] as? String ?? "",
                    ok: row["ok"] as? Bool ?? true
                )
            }
        }
    }

    private func loadCharactersIfNeeded() {
        guard characters.isEmpty else { return }
        Task { @MainActor in
            let result = await AgentBridge.shared.query("characters")
            guard result.ok, let data = result.json else { return }
            characters = (try? JSONDecoder().decode([OnboardingCharacter].self, from: data)) ?? []
        }
    }

    private func pickCharacter(path: String, id: String) {
        guard !busy else { return }
        busy = true
        errorText = nil
        Task { @MainActor in
            let outcome = await gate.chooseCharacter(path: path, characterId: id)
            busy = false
            switch outcome {
            case .success(let next):
                guard let next else { onFinish(); return }
                turn = next
                spoken = false
                speakCurrentTurn()
            case .failure(let failure):
                errorText = failure.message
            }
        }
    }

    // MARK: - Narration-time listening (barge-in)

    /// Listen WHILE the installer talks, with a close-talk threshold.
    ///
    /// The detector suppresses onset while TTS output is active because
    /// there is no echo cancellation — the mic would otherwise hear the
    /// speakers. A close-talk threshold (−30 dBFS onset) sits well above
    /// speaker bleed at conversational volume but under a person speaking
    /// from a metre away, so a real interruption still trips onset while
    /// narration plays. The tap is monitor-only: frames are scored and
    /// dropped, nothing is retained.
    private static let bargeInVAD: VADConfiguration = {
        var config = VADConfiguration.default
        config.onsetThresholdDB = -30
        config.releaseThresholdDB = -38
        return config
    }()

    private func startBargeInMonitoring() {
        guard VoiceRecorder.hasAudioInput else { return }
        Task { @MainActor in
            let granted = await VoiceRecorder.requestMicrophoneAccess()
            guard granted, VoiceRecorder.hasAudioInput else { return }
            // FirstBootView is a struct: the closure captures it by value
            // (same pattern as the answerRecorder callbacks below), and
            // @State/@StateObject wrappers remain reference-backed.
            bargeInRecorder.onSpeechOnset = {
                handleBargeIn()
            }
            bargeInRecorder.onSpeechEnded = nil
            bargeInRecorder.speechDetector.update(
                configuration: Self.bargeInVAD)
            // Output is active right now (this call precedes the utterance
            // being queued) — without suppression the speakers' voice is
            // the loudest thing the mic hears.
            bargeInRecorder.speechDetector.setOutputActive(true)
            try? bargeInRecorder.startMonitoring()
        }
    }

    private func stopBargeInMonitoring() {
        bargeInRecorder.onSpeechOnset = nil
        bargeInRecorder.onSpeechEnded = nil
        bargeInRecorder.stopMonitoring()
    }

    /// The operator talked over the installer. Stop the voice immediately
    /// — local stop first, exactly as the chat-side ambient loop does —
    /// and keep the sequence on this turn so the installer's focus is
    /// kept. The text is already on screen; the interrupted words are not
    /// lost to someone who was mid-sentence with their own thought.
    private func handleBargeIn() {
        narrationTask?.cancel()
        tts.stop()
        bargeInRecorder.speechDetector.setOutputActive(false)
        ambient.armResponseClock()
    }

    /// Speak the turn in the stage's voice.
    ///
    /// Setup uses a fixed technical Kokoro voice. State 3 swaps the same
    /// speech engine to the calibrated agent voice
    /// persona immediately before the handoff line, so the first thing the
    /// operator hears in the new voice is "*(clears throat)* Hello, I'm
    /// here." — the change of voice is the moment, not a side effect of it.
    private func speakCurrentTurn() {
        guard gate.setupError == nil else { return }
        guard !spoken else { return }
        spoken = true
        startBargeInMonitoring()

        // Arm the response clock as the prompt ENDS, so latency measures
        // how long they took to answer rather than how long we talked.
        narrationTask?.cancel()

        if turn.isPersonaHandoff {
            // The installer finishes its own farewell before the new voice
            // arrives. Do not speak both speakers as one utterance.
            tts.enterVoiceStage(.installer)
            if let profile = gate.voiceProfile {
                gate.applyVoiceProfile(profile, to: tts)
            }
            narrationTask = Task { @MainActor in
                try? await Task.sleep(for: .milliseconds(700))
                guard !Task.isCancelled else { return }
                let completed = await tts.speakAndWait(turn.lines.first ?? "")
                guard !Task.isCancelled else { return }
                tts.enterVoiceStage(.persona)
                personaArrived = true
                if completed {
                    try? await Task.sleep(for: .milliseconds(850))
                    guard !Task.isCancelled else { return }
                    tts.speak(turn.lines.dropFirst().joined(separator: "\n\n"))
                } else {
                    errorText = "Speech is unavailable. You can read the introduction and continue."
                }
            }
        } else {
            tts.enterVoiceStage(.installer)
            let status = gate.status
            let leadIn = narrationLeadIn
            narrationTask = Task { @MainActor in
                if leadIn > .zero {
                    try? await Task.sleep(for: leadIn)
                    guard !Task.isCancelled, gate.status == status else { return }
                }
                let completed = await tts.speakAndWait(turn.text)
                guard !Task.isCancelled, gate.status == status else { return }
                if !completed {
                    errorText = tts.lastError
                        ?? "The neural setup voice is unavailable. You can continue using text."
                }
                ambient.armResponseClock()
                if turn.awaitsReply && !isBenchTurn && !isCharacterTurn {
                    beginAnswerRecording(automatic: true)
                }
                if questionKey == "q2" {
                    startTruncationWatch()
                }
            }
        }
    }

    /// Cut the operator off mid-narrative once Probe 3 has yielded enough.
    ///
    /// The interruption IS the design: the installer is an instrument that
    /// has finished measuring, and its indifference to an unfinished
    /// sentence is what makes the warmth that follows land. Waiting for a
    /// natural ending would gather nothing further and lose the moment.
    private func startTruncationWatch() {
        truncationWatch?.cancel()
        truncationWatch = Task { @MainActor in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 250_000_000)
                if Task.isCancelled { return }
                guard ambient.elapsedSpeechSeconds >= Self.truncateAfterSeconds
                else { continue }
                truncate()
                return
            }
        }
    }

    /// Stop listening, speak the exit line, and advance.
    private func truncate() {
        truncationWatch?.cancel()
        truncationWatch = nil
        // Close the mic BEFORE speaking: the exit line must not be heard by
        // a tap that is still scoring frames, and a hard stop here is right
        // — this is a deliberate cut, not a graceful ending.
        ambient.recorder.stopMonitoring()
        stopBargeInMonitoring()
        tts.stop()

        Task { @MainActor in
            // Telemetry comes from the recorder that captured the answer
            // (answerRecorder), not the ambient monitor — monitor-mode
            // taps drop frames instead of retaining them, so the ambient
            // side never measures delivery.
            let telemetry = (
                latencyMs: answerRecorder.speechDetector.onsetLatencyMs,
                energyVariance: answerRecorder.speechDetector.energyVariance,
            )
            _ = await gate.submit(
                question: "q2",
                reply: reply.trimmingCharacters(in: .whitespacesAndNewlines),
                latencyMs: telemetry.latencyMs,
                energyVariance: telemetry.energyVariance,
            )
            if case .onboard(let next) = await gate.evaluate() {
                turn = next
                spoken = false
                speakCurrentTurn()
            }
        }
    }

    private func submit() {
        truncationWatch?.cancel()
        truncationWatch = nil
        stopBargeInMonitoring()
        if turn.isPersonaHandoff {
            Task { await finishHandoff() }
            return
        }
        let answer = reply.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !answer.isEmpty, !busy, !transcribing, !answerRecorder.isRecording else { return }

        busy = true
        errorText = nil
        Task {
            // Ship the acoustic evidence with the answer — without it the
            // backend sees hedging words but not a long silent pause, so a
            // delayed confident reply would read as confidence.
            let outcome = await gate.submit(
                question: questionKey, reply: answer,
                latencyMs: answerRecorder.speechDetector.onsetLatencyMs,
                energyVariance: recordedEnergyVariance,
            )
            busy = false
            switch outcome {
            case .success(let next):
                reply = ""
                recordedEnergyVariance = nil
                // Record the preference WITHOUT changing what is speaking.
                // An earlier version applied it here so the operator would
                // "hear their choice sooner"; that spends the handoff a
                // turn early and State 3 then arrives in a voice they have
                // already been listening to. The swap belongs at the
                // handoff and nowhere else.
                if let profile = gate.voiceProfile {
                    gate.applyVoiceProfile(profile, to: tts)
                }
                guard let next else { onFinish(); return }
                turn = next
                spoken = false
                speakCurrentTurn()

            case .failure(let failure):
                // `unclear_voice_answer` means the backend declined to
                // guess. Re-ask rather than assigning a voice they did not
                // choose on the very first thing they said.
                errorText = failure.message == "unclear_voice_answer"
                    ? "Sorry — male or female?"
                    : failure.message
                reply = answer
            }
        }
    }

    private func toggleAnswerRecording() {
        if !answerRecorder.isRecording {
            narrationTask?.cancel()
            tts.stop()
            beginAnswerRecording(automatic: false)
            return
        }
        finishAnswerRecording(autoSubmit: automaticListening)
    }

    /// Begin a real conversational listen after the installer finishes its
    /// prompt. The first call is also the appropriate point for macOS to show
    /// its native microphone permission dialog: the person has just heard why
    /// Jaeger needs the microphone and capture has not started yet.
    private func beginAnswerRecording(automatic: Bool) {
        guard !answerRecorder.isRecording, !requestingMicrophone else { return }
        requestingMicrophone = true
        Task { @MainActor in
            let granted = await VoiceRecorder.requestMicrophoneAccess()
            requestingMicrophone = false
            guard granted else {
                automaticListening = false
                errorText = "Microphone access is off. Enable JaegerAI in System Settings → Privacy & Security → Microphone."
                return
            }
            microphoneAvailable = VoiceRecorder.hasAudioInput
            guard microphoneAvailable else {
                automaticListening = false
                errorText = "No microphone is connected. Connect an input device and press Check again."
                return
            }
            do {
                automaticListening = automatic
                answerRecorder.onSpeechOnset = {
                    ambient.armResponseClock()
                }
                answerRecorder.onSpeechEnded = {
                    guard automaticListening else { return }
                    finishAnswerRecording(autoSubmit: true)
                }
                try answerRecorder.startRecording()
                answerRecorder.speechDetector.markPromptEnded()
                errorText = nil
            } catch {
                automaticListening = false
                errorText = "Microphone unavailable: \(error.localizedDescription). You can type instead."
            }
        }
    }

    /// Close the mic, run local Whisper, and in conversational mode submit
    /// the transcript immediately. Manual push-to-talk still leaves the text
    /// editable, preserving the existing fallback path.
    private func finishAnswerRecording(autoSubmit: Bool) {
        automaticListening = false
        answerRecorder.stopRecording()
        recordedEnergyVariance = answerRecorder.speechDetector.energyVariance
        guard let captured = answerRecorder.takeCapturedAudio() else {
            errorText = "No speech was captured. Try again or type your answer."
            return
        }
        transcribing = true
        STTManager.shared.transcribe(samples: captured.samples, format: captured.format) { result in
            MainActor.assumeIsolated {
                transcribing = false
                switch result {
                case .success(let value):
                    reply = value.text
                    if autoSubmit { submit() }
                case .failure(let error): errorText = "Could not transcribe: \(error.localizedDescription). You can type instead."
                }
            }
        }
    }

    private func finishHandoff() async {
        busy = true
        let completed = await gate.complete()
        busy = false
        if completed {
            AgentBridge.shared.onboardingDidFinish()
            onFinish()
            ChatWindowController.show(agent: AgentBridge.shared)
        } else {
            errorText = "Could not finish initiation. Please try again."
        }
    }
}


private struct FirstBootActionStyle: ButtonStyle {
    var primary = false
    @Environment(\.isEnabled) private var enabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: primary ? 14 : 13, weight: .semibold))
            .foregroundStyle(primary ? Color.white : Term.accent)
            .padding(.horizontal, primary ? 26 : 16)
            .padding(.vertical, primary ? 12 : 9)
            .background(Capsule().fill(primary ? Term.accent : Term.accent.opacity(0.10)))
            .opacity(enabled ? (configuration.isPressed ? 0.75 : 1) : 0.4)
    }
}
