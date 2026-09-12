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
        panel.setContentSize(NSSize(width: 560, height: 360))
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

    private let tts = TTSManager.shared

    init(gate: FirstBootGate, firstTurn: FirstBootGate.Turn, onFinish: @escaping () -> Void) {
        self.gate = gate
        self.firstTurn = firstTurn
        self.onFinish = onFinish
        _turn = State(initialValue: firstTurn)
    }

    /// Which question the current turn is asking, in the backend's terms.
    private var questionKey: String {
        gate.status == "AWAITING_Q2" ? "q2" : "voice"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            ForEach(Array(turn.lines.enumerated()), id: \.offset) { _, line in
                Text(line)
                    .font(line == turn.lines.first && turn.lines.count > 1
                          ? .system(size: 15, weight: .regular)
                          : .system(size: 19, weight: .medium))
                    .foregroundStyle(line == turn.lines.first && turn.lines.count > 1
                                     ? .secondary : .primary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if turn.awaitsReply && !turn.isPersonaHandoff {
                TextField("", text: $reply, prompt: Text("Your answer"))
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 15))
                    .onSubmit { submit() }
                    .disabled(busy)
            }

            if let errorText {
                Text(errorText)
                    .font(.system(size: 13))
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 0)

            HStack {
                // Deferring is allowed and recorded — first boot resumes
                // where it left off. Silently abandoning it is not.
                Button("Not now") { onFinish() }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
                Spacer()
                if busy { ProgressView().controlSize(.small) }
                Button(turn.isPersonaHandoff ? "Continue" : "Send") { submit() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(busy || (!turn.isPersonaHandoff && reply.trimmingCharacters(
                        in: .whitespacesAndNewlines).isEmpty))
            }
        }
        .padding(28)
        .frame(minWidth: 520, minHeight: 320, alignment: .topLeading)
        .onAppear { speakCurrentTurn() }
    }

    /// Speak the turn in the right voice. States 1 and 2 use the neutral
    /// installer voice; State 3 is the initialized persona, and that change
    /// of voice IS the handoff the operator is meant to notice.
    private func speakCurrentTurn() {
        guard !spoken else { return }
        spoken = true
        tts.speak(turn.text)
    }

    private func submit() {
        if turn.isPersonaHandoff {
            Task { await finishHandoff() }
            return
        }
        let answer = reply.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !answer.isEmpty, !busy else { return }

        busy = true
        errorText = nil
        Task {
            let outcome = await gate.submit(question: questionKey, reply: answer)
            busy = false
            switch outcome {
            case .success(let next):
                reply = ""
                // State 1 answered: apply the chosen voice before the next
                // line is spoken, so the operator hears their choice
                // immediately rather than one turn later.
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
        _ = await gate.complete()
        busy = false
        onFinish()
    }
}
