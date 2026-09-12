//
//  FirstBootGate.swift
//  JaegerAI / Onboarding
//
//  The OS 1 launch gate. On client start it asks the bridge where this
//  identity got to in first boot; if the welcome has not completed, the
//  app opens straight into it instead of the ordinary idle menu bar.
//
//  State of record is `<instance>/first_boot.yaml`, owned by
//  `jaeger_ai.core.instance.first_boot` — NOT the gateway session DB.
//  First-boot state belongs to one identity; the gateway DB is per-host
//  session storage. Keeping the flag in both is how a system ends up with
//  two answers to "has this person met their SI yet".
//
//  This type holds no copy of its own. The greeting, the two questions and
//  the handoff live in `first_boot_script.py` and arrive over the bridge,
//  so the wording cannot drift between the Swift client, the WebUI and the
//  TUI — the sequence is a product invariant and there is exactly one
//  place it is written down.
//

import Foundation

@MainActor
final class FirstBootGate: ObservableObject {

    /// What the client should do on launch.
    enum Decision: Equatable, Sendable {
        /// Welcome finished (or migrated) — go straight to normal operation.
        case proceed
        /// Show the onboarding window; `turn` is what OS 1 says first.
        case onboard(Turn)
        /// The bridge could not answer. Deliberately NOT `.proceed`:
        /// guessing "finished" would skip a new operator's welcome forever,
        /// and guessing "not started" would replay it for an existing one.
        case unavailable(String)
    }

    /// Why a first-boot step could not proceed.
    struct Failure: Error, LocalizedError, Equatable {
        let message: String
        var errorDescription: String? { message }
    }

    /// One scripted turn, decoded from the bridge's `first_boot` query.
    struct Turn: Equatable, Sendable {
        /// `"os1"` for the neutral installer voice, `"persona"` once the
        /// initialized SI takes over. Drives which voice speaks.
        let speaker: String
        let lines: [String]
        let text: String
        let awaitsReply: Bool

        var isPersonaHandoff: Bool { speaker == "persona" }
    }

    @Published private(set) var decision: Decision?
    @Published private(set) var status: String = "unknown"
    @Published private(set) var voiceProfile: String?

    private let bridge: AgentBridge

    init(bridge: AgentBridge) {
        self.bridge = bridge
    }

    // MARK: - Launch gate

    /// Ask the bridge whether to open onboarding. Call once at startup,
    /// before showing the idle menu bar.
    @discardableResult
    func evaluate() async -> Decision {
        let result = await bridge.query("first_boot")
        guard result.ok, let data = result.json else {
            let decision = Decision.unavailable(result.error ?? "bridge unavailable")
            self.decision = decision
            self.status = "unavailable"
            return decision
        }

        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            let decision = Decision.unavailable("malformed first_boot payload")
            self.decision = decision
            return decision
        }

        status = object["status"] as? String ?? "unknown"
        voiceProfile = object["voice_profile"] as? String

        let complete = object["complete"] as? Bool ?? false
        if complete {
            decision = .proceed
            return .proceed
        }

        guard let turnObject = object["turn"] as? [String: Any],
              let decoded = Self.decodeTurn(turnObject) else {
            // Not complete, but no turn to show. Treat as unavailable rather
            // than silently proceeding — the operator would otherwise never
            // see a welcome that the backend still believes is pending.
            let decision = Decision.unavailable("first boot pending but no turn returned")
            self.decision = decision
            return decision
        }

        decision = .onboard(decoded)
        return .onboard(decoded)
    }

    // MARK: - Answering

    /// Submit an answer and return the next turn, or `nil` when finished.
    ///
    /// `question` is `"voice"` or `"q2"`. Every transition underneath is
    /// idempotent, so a double-submitted answer lands on the same state
    /// rather than advancing twice.
    func submit(question: String, reply: String) async -> Result<Turn?, Failure> {
        let result = await bridge.command(
            "first_boot_answer", args: ["question": question, "reply": reply],
        )
        guard result.ok else {
            // `unclear_voice_answer` is the backend declining to guess when
            // the reply names neither or both. Surface it so the caller
            // re-asks rather than assigning a voice the operator never chose.
            return .failure(Failure(message: result.error ?? "answer rejected"))
        }

        switch await evaluate() {
        case .onboard(let next):      return .success(next)
        case .proceed:                return .success(Turn?.none)
        case .unavailable(let reason): return .failure(Failure(message: reason))
        }
    }

    /// Mark the welcome finished. Called after the persona's first words.
    ///
    /// `personaName` records the name the SI chose for itself; first write
    /// wins, so a retried completion cannot rename an SI the operator has
    /// already met.
    func complete(personaName: String? = nil) async -> Bool {
        var args: [String: any Sendable] = [:]
        if let personaName, !personaName.isEmpty { args["persona_name"] = personaName }
        let result = await bridge.command("first_boot_complete", args: args)
        if result.ok {
            decision = .proceed
            status = "COMPLETED"
        }
        return result.ok
    }

    // MARK: - Voice

    /// Apply the operator's State 1 choice to the speech layer.
    ///
    /// `voice_profile` is an experience (`male`/`female`), deliberately not
    /// a vendor voice id — the capability router maps it onto whichever
    /// engine is installed. Passing `am_michael` here would weld the
    /// operator's first decision to one TTS backend forever.
    func applyVoiceProfile(_ profile: String, to tts: TTSManager) {
        voiceProfile = profile
        tts.preferredVoiceProfile = profile
    }

    // MARK: - Decoding

    private static func decodeTurn(_ object: [String: Any]) -> Turn? {
        guard let speaker = object["speaker"] as? String,
              let text = object["text"] as? String else { return nil }
        return Turn(
            speaker: speaker,
            lines: object["lines"] as? [String] ?? [text],
            text: text,
            awaitsReply: object["awaits_reply"] as? Bool ?? true
        )
    }
}
