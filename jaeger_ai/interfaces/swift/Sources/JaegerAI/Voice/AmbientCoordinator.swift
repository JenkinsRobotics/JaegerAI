//
//  AmbientCoordinator.swift
//  JaegerAI / Voice
//
//  App-lifetime owner of the ambient voice loop.
//
//  Nothing owned ``AmbientLoop`` before this: it was never constructed, and
//  the only ``VoiceRecorder`` belonged to a chat window, so it died with
//  that window. Barge-in needs a microphone that outlives any one view —
//  the operator interrupts whatever is speaking, from wherever they are.
//
//  Monitoring policy. An always-open microphone is a real cost (battery,
//  and the plain fact of an open mic), so it is NOT on by default. It opens
//  when there is something to interrupt and closes when there is not:
//
//      speaking / thinking  ──► monitoring ON    (you can talk over it)
//      idle / interrupted   ──► monitoring OFF   (nothing to interrupt)
//      muted                ──► always OFF       (operator override)
//
//  Buffers are scored and dropped while monitoring — nothing is retained,
//  so this is a level meter, not a recording.
//

import Foundation
import os

@MainActor
final class AmbientCoordinator: ObservableObject {

    static let shared = AmbientCoordinator()

    /// Operator kill switch. When false the mic never opens, whatever the
    /// loop is doing — a mute the software cannot talk itself out of.
    @Published var isEnabled: Bool = true {
        didSet { reconcileMonitoring() }
    }

    @Published private(set) var isMonitoring: Bool = false
    @Published private(set) var lastError: String?

    let loop: AmbientLoop
    let recorder = VoiceRecorder()

    private let log = Logger(subsystem: "com.jenkinsrobotics.JaegerAI",
                             category: "AmbientCoordinator")
    private var stateObservation: Task<Void, Never>?

    init(
        gateway: GatewayClient = .fromEnvironment(),
        tts: TTSManager = .shared
    ) {
        self.loop = AmbientLoop(
            gateway: gateway, tts: tts, detector: recorder.speechDetector,
        )
    }

    // MARK: - Lifecycle

    /// Wire the tap to the loop. Call once at startup.
    ///
    /// Does NOT open the mic — ``reconcileMonitoring`` does that when the
    /// loop has something to interrupt. Attaching and opening are separate
    /// so a client can be fully wired and still silent.
    func activate() {
        loop.recorder = recorder
        recorder.onSpeechOnset = { [weak self] in
            guard let self, self.isEnabled else { return }
            self.loop.handleSpeechOnset()
            self.reconcileMonitoring()
        }
        recorder.onSpeechEnded = { [weak self] in
            guard let self else { return }
            self.loop.handleSpeechEnded()
            self.reconcileMonitoring()
        }
        observeLoopState()
        log.info("ambient coordinator activated")
    }

    /// Release the mic and unhook. Call on terminate.
    func deactivate() {
        stateObservation?.cancel()
        stateObservation = nil
        recorder.onSpeechOnset = nil
        recorder.onSpeechEnded = nil
        stopMonitoring()
        loop.stop()
    }

    // MARK: - Monitoring policy

    /// Open or close the mic to match the loop's state and the mute flag.
    ///
    /// Idempotent: safe to call on every state change, and the recorder's
    /// own guards make a redundant start/stop a no-op.
    func reconcileMonitoring() {
        let wanted = isEnabled && Self.needsMicrophone(for: loop.state)
        if wanted { startMonitoring() } else { stopMonitoring() }
    }

    /// Whether a state is one the operator can interrupt.
    ///
    /// ``.speaking`` is the obvious case. ``.thinking`` is included on
    /// purpose: a turn is in flight and cancelling it before the first
    /// word is a legitimate interrupt — waiting for audio to start would
    /// make the earliest, most deliberate interruption the one that fails.
    static func needsMicrophone(for state: AmbientState) -> Bool {
        switch state {
        case .speaking, .thinking, .listening: return true
        case .idle, .interrupted:              return false
        }
    }

    private func startMonitoring() {
        guard !isMonitoring else { return }
        do {
            try recorder.startMonitoring()
            isMonitoring = true
            lastError = nil
        } catch {
            // A machine with no input device is normal (headless, no mic
            // permission yet). Barge-in is simply unavailable — surfaced,
            // not fatal, and never retried in a tight loop.
            isMonitoring = false
            lastError = "microphone unavailable: \(error.localizedDescription)"
            log.warning("monitoring unavailable: \(error.localizedDescription, privacy: .public)")
        }
    }

    private func stopMonitoring() {
        guard isMonitoring else { return }
        recorder.stopMonitoring()
        isMonitoring = false
    }

    /// Follow the loop's state so the mic tracks it without every call site
    /// having to remember to reconcile.
    private func observeLoopState() {
        stateObservation?.cancel()
        stateObservation = Task { [weak self] in
            guard let self else { return }
            var last = self.loop.state
            while !Task.isCancelled {
                if self.loop.state != last {
                    last = self.loop.state
                    self.reconcileMonitoring()
                }
                try? await Task.sleep(nanoseconds: 120_000_000)   // 120 ms
            }
        }
    }
}
