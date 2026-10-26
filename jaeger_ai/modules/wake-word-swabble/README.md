# wake-word-swabble — independent module, NOT yet wired

Job: local-only wake-word gating for Jaeger, so Jaeger can listen without always listening to everything, and without sending audio to a cloud service to decide if it was spoken to. This is a gap in the current stack: Jaeger has Whisper STT + Kokoro TTS and menubar voice, but NO wake-word gate in the repo (search for "swabble" in JaegerAI returned 0 matches, 2026-10-22).

Source, NOT copied into this module (third-party upstream, do not claim it as Jaeger code):
- Desktop "Ai  work " folder (name has a double space + trailing space, open it via a trailing slash, not by the bare folder name) / JaegerAI_Archive/apps_swabble/ — README.md 4,248 bytes, Package.swift 1,694, LICENSE 1,076, CHANGELOG.md, Sources/, Tests/, docs/, scripts/.
- Upstream, per that README: https://github.com/steipete/swabble.git, branch main. Swift 6.2, CLI targets macOS 26 (SpeechAnalyzer + SpeechTranscriber), shared SwabbleKit target is multi-platform and exposes wake-word gating utilities for iOS/macOS apps.
- Local-only: Speech.framework on-device models, zero network usage. That fits Jaeger TRUST.md (senses stay on device) and Apple-first direction.
- Default wake word in that README is "clawd" (aliases "claude") — that is the upstream default, NOT a Jaeger wake word. Do NOT wire Jaeger to answer to "clawd"/"claude" by default. The operator must pick a wake word first.
- Features in that README: hooks (run any command with prefix/env, cooldown, min_chars, timeout), file transcribe to TXT or SRT with time ranges, launchd helper stubs for start/stop/install, `swift run swabble setup / serve / test-hook`.

How it bolts on (IDE agent, wire later, do NOT wire by copying Hermes/Claude hooks):
- Swabble hook -> Jaeger Gateway turn, via the Gateway approval gate, NOT directly to a shell command that can act. Wake word is a trigger, not permission. A turn started by a wake word still needs the same proposer/checker/approval rules as any other turn, especially for irreversible actions.
- SwabbleKit as a library in the macos-shell / iOS client, not as a second voice system. Jaeger voice (Whisper/Kokoro) stays the speech engine; Swabble is only the gate in front of it.
- Check license + Swift version first: upstream is a separate project, macOS 26 target may not match the current macOS version, and the README's install script path (../../scripts/install-swift-tools.sh) is archive-relative, not repo-relative.

Test to run when code-run is available: build swabble, set a test wake word, speak it, hook fires once (cooldown respected), no audio leaves the device, Jaeger turn starts and approval gate still applies, non-wake speech does NOT fire.
