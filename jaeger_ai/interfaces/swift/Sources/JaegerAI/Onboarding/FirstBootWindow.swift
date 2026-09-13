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

        let panel = NSWindow(contentViewController: hosting)
        panel.title = "OS 1"
        panel.styleMask = [.titled, .fullSizeContentView]
        panel.titlebarAppearsTransparent = true
        panel.titleVisibility = .hidden
        panel.isMovableByWindowBackground = true
        panel.setContentSize(NSSize(width: 620, height: 480))
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
    @State private var characters: [(id: String, name: String)] = []
    @State private var benchTask: Task<Void, Never>?

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
    }

    /// Which question the current turn is asking, in the backend's terms.
    private var questionKey: String {
        switch gate.status {
        case "AWAITING_BENCH":     return "bench"
        case "AWAITING_CHARACTER": return "character"
        case "AWAITING_SOCIAL":    return "social"
        case "AWAITING_HESITANCE": return "hesitance"
        case "AWAITING_Q2":        return "q2"
        default:                   return "voice"
        }
    }

    private var isBenchTurn: Bool { gate.status == "AWAITING_BENCH" || questionKey == "bench" }
    private var isCharacterTurn: Bool { gate.status == "AWAITING_CHARACTER" }

    private var visibleLines: [String] {
        guard turn.isPersonaHandoff else { return turn.lines }
        return personaArrived ? Array(turn.lines.dropFirst()) : Array(turn.lines.prefix(1))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("JENKINS ROBOTICS · JAEGER AI OS1")
                .font(.system(size: 10, weight: .semibold))
                .kerning(1.6)
                .foregroundStyle(.secondary)

            ForEach(Array(visibleLines.enumerated()), id: \.offset) { _, line in
                Text(line)
                    .font(line == turn.lines.first && turn.lines.count > 1
                          ? .system(size: 15, weight: .regular)
                          : .system(size: 19, weight: .medium))
                    .foregroundStyle(line == turn.lines.first && turn.lines.count > 1
                                     ? .secondary : .primary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if isBenchTurn {
                benchPanel
            }

            if isCharacterTurn {
                characterPanel
            }

            if turn.awaitsReply && !turn.isPersonaHandoff && !isCharacterTurn && !isBenchTurn {
                TextField("", text: $reply, prompt: Text("Your answer"))
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 15))
                    .onSubmit { submit() }
                    .disabled(busy)
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

            Spacer(minLength: 0)

            HStack {
                Button("Not now") { onFinish() }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
                Spacer()
                if busy { ProgressView().controlSize(.small) }
                if isBenchTurn {
                    Text(benchStatus == "done" ? "Bench complete" : "Measuring…")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                } else if !isCharacterTurn {
                    Button(turn.isPersonaHandoff ? "Continue" : "Send") { submit() }
                        .keyboardShortcut(.defaultAction)
                        .disabled(busy || (turn.isPersonaHandoff && !personaArrived) || (!turn.isPersonaHandoff && reply.trimmingCharacters(
                            in: .whitespacesAndNewlines).isEmpty))
                }
            }
        }
        .padding(28)
        .frame(minWidth: 580, minHeight: 420, alignment: .topLeading)
        .onAppear {
            speakCurrentTurn()
            if isBenchTurn { startBenchIfNeeded() }
            if isCharacterTurn { loadCharactersIfNeeded() }
        }
        .onChange(of: gate.status) { _, newStatus in
            if newStatus == "AWAITING_BENCH" { startBenchIfNeeded() }
            if newStatus == "AWAITING_CHARACTER" { loadCharactersIfNeeded() }
        }
        .onDisappear {
            truncationWatch?.cancel()
            benchTask?.cancel()
            tts.stop()
            tts.enterVoiceStage(.persona)
        }
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
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.primary.opacity(0.05)))
    }

    private var characterPanel: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Preset or custom")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(.secondary)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(characters, id: \.id) { character in
                        Button(character.name) {
                            pickCharacter(path: "preset", id: character.id)
                        }
                        .buttonStyle(.bordered)
                        .disabled(busy)
                    }
                }
            }
            Button("Custom — calibrate with mic questions") {
                pickCharacter(path: "custom", id: "assistant")
            }
            .keyboardShortcut(.defaultAction)
            .disabled(busy)
        }
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
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.primary.opacity(0.05)))
    }


    private func startBenchIfNeeded() {
        guard benchTask == nil else { return }
        benchTask = Task { @MainActor in
            busy = true
            defer { busy = false }
            guard let started = await gate.startHardwareBench() else {
                errorText = "Hardware bench could not start."
                return
            }
            benchId = started["id"] as? String
            applyBenchPayload(started)
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 400_000_000)
                guard let snap = await gate.hardwareBenchStatus(id: benchId) else { continue }
                applyBenchPayload(snap)
                let status = snap["status"] as? String ?? ""
                if status == "done" || status == "error" {
                    if status == "error" {
                        errorText = snap["error"] as? String ?? "Hardware bench failed"
                    }
                    let outcome = await gate.completeBench(benchId: benchId)
                    switch outcome {
                    case .success(let next):
                        guard let next else { onFinish(); return }
                        turn = next
                        spoken = false
                        speakCurrentTurn()
                        loadCharactersIfNeeded()
                    case .failure(let failure):
                        errorText = failure.message
                    }
                    return
                }
            }
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
            guard result.ok, let data = result.json,
                  let arr = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]]
            else { return }
            characters = arr.compactMap { row in
                guard let id = row["id"] as? String else { return nil }
                let name = (row["name"] as? String) ?? (row["display_name"] as? String) ?? id
                return (id: id, name: name)
            }
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

    /// Speak the turn in the stage's voice.
    ///
    /// Setup uses a fixed technical Kokoro voice. State 3 swaps the same
    /// speech engine to the calibrated agent voice
    /// persona immediately before the handoff line, so the first thing the
    /// operator hears in the new voice is "*(clears throat)* Hello, I'm
    /// here." — the change of voice is the moment, not a side effect of it.
    private func speakCurrentTurn() {
        guard !spoken else { return }
        spoken = true

        // Arm the response clock as the prompt ENDS, so latency measures
        // how long they took to answer rather than how long we talked.
        ambient.armResponseClock()
        if questionKey == "q2" { startTruncationWatch() }

        if turn.isPersonaHandoff {
            // The installer finishes its own farewell before the new voice
            // arrives. Do not speak both speakers as one utterance.
            tts.enterVoiceStage(.installer)
            if let profile = gate.voiceProfile {
                gate.applyVoiceProfile(profile, to: tts)
            }
            Task { @MainActor in
                let completed = await tts.speakAndWait(turn.lines.first ?? "")
                guard completed else { return }
                tts.enterVoiceStage(.persona)
                personaArrived = true
                tts.speak(turn.lines.dropFirst().joined(separator: "\n\n"))
            }
        } else {
            tts.enterVoiceStage(.installer)
            tts.speak(turn.text)
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
        tts.stop()

        Task { @MainActor in
            let telemetry = ambient.probeTelemetry
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
        if turn.isPersonaHandoff {
            Task { await finishHandoff() }
            return
        }
        let answer = reply.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !answer.isEmpty, !busy else { return }

        busy = true
        errorText = nil
        Task {
            // Ship the acoustic evidence with the answer — without it the
            // backend sees hedging words but not a long silent pause, so a
            // delayed confident reply would read as confidence.
            let telemetry = ambient.probeTelemetry
            let outcome = await gate.submit(
                question: questionKey, reply: answer,
                latencyMs: telemetry.latencyMs,
                energyVariance: telemetry.energyVariance,
            )
            busy = false
            switch outcome {
            case .success(let next):
                reply = ""
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

    private func finishHandoff() async {
        busy = true
        let completed = await gate.complete()
        busy = false
        if completed {
            onFinish()
            ChatWindowController.show(agent: AgentBridge.shared)
        } else {
            errorText = "Could not finish initiation. Please try again."
        }
    }
}
