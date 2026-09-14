# Live desktop and multimodal verification — 2026-09-07

Follow-up to the [CPU-only desktop checks](DESKTOP_CPU_VERIFICATION_20260904.md).
GPU use was explicitly authorized for this pass. Changes remain local; nothing
was committed, pushed, or released.

## Live installed-app checks

Launched `/Applications/Jaeger AI.app` through macOS LaunchServices (`open`),
using a fresh temporary instance derived from `jaeger-dev`. Normal user memory
and workspace were not used for test turns. The app reached **Standing by**.

- Opened Multimodal using its actual native menu-card button, then Chat and
  Avatar using their buttons. Multimodal did not crash the agent.
- Submitted `Reply with only DESKTOP-READY.` through the actual Multimodal input
  and Send button. The displayed response was `DESKTOP-READY`.
- Initial settings were **Half-Duplex**, **Agentic**, and dynamic output.
- The microphone opened on the Elgato XLR Dock. Its mute control changed the
  telemetry to MUTED. Camera discovery selected HD Pro Webcam C920, but camera
  access was not granted; the original view incorrectly remained “starting…”.
- Switched through Quasi Full-Duplex and Full-Duplex using the actual selector.
  Both reported the engine-owned 48 kHz AEC device active. Two input-overflow
  warnings appeared during switching. No acoustic-quality certification follows
  from starting those streams, especially with the microphone subsequently muted.
- Process inspection showed one native app, one bridge, and one thin Qt helper.
  The helper used approximately 216 MB RSS while the bridge held the model stack.
  Gemma, Whisper, and Kokoro were not loaded again in the helper.
- macOS `NSRunningApplication` reported activation policy **0 (regular)** for
  the native app and **1 (accessory)** for its Qt helper. Both had icons. This
  verifies one Dock-owning app rather than a second generic Python Dock entry.
- Quitting the native app terminated that app, bridge, and helper. No test-owned
  model process from the first live run remained. This was idle shutdown, not
  cancellation of an arbitrary in-progress side-effecting tool.

The first native launch took approximately **80 seconds** to reach readiness;
the log attributed **60.6 seconds** to the `desktop-app` prompt prewarm. The
model file itself loaded in 3.7 seconds. This is not reference-equivalent
startup. The ordinary desktop launch exposes the default full tool surface;
the recorded benchmark explicitly uses `JAEGER_TOOLSET_SCOPING=1`. These
startup configurations must not be conflated. The agentic loop/tool policy was
not changed to improve a benchmark number.

## Fixes made from live findings

Paths are relative to JaegerAI:

- `jaeger_ai/interfaces/pyside6/multimodal/window.py:1202`: check camera
  permission before starting capture; request an undetermined permission once;
  explain denial with System Settings guidance rather than pretending to start.
- `window.py:1234`: a late permission response cannot turn video back on after
  the operator has turned it off. Closing the window also clears that intent.
- `window.py:1321`: deferred session/camera autostart checks window visibility;
  context-bound timers are canceled when their QObject is destroyed.
- `window.py:378`: wrap camera status text within the preview panel.
- `window.py:418`: give the message field its own full-width row, above the
  attachment/mode/send controls; the original field was only a few characters
  wide in the actual four-column desktop layout.
- `jaeger_ai/interfaces/swift/Sources/JaegerOS/Avatar/AvatarWindows.swift:18`:
  native Avatar titles now consistently begin with **Jaeger AI**.
- `jaeger_ai/interfaces/swift/Sources/JaegerOS/Multimodal/MultimodalWindowController.swift`:
  request camera consent from the native app before launching its helper. Live
  revalidation exposed Qt's `NSCameraUsageDescription` check against the Python
  helper's own bundle, despite the parent bundle already containing that key.
  The native app now owns consent; denial still permits the text/audio UI to
  open. Added native tests for authorized, denied, restricted, and undetermined
  states without requesting any real permissions in unit tests.
- `jaeger_ai/interfaces/swift/Scripts/build-app.sh`: embed the environment's
  Python executable as `Contents/MacOS/JaegerMultimodal`, sign it, and record
  its Python base/site-package paths. The controller launches the canonical
  face with that executable and processes the existing environment's editable
  package registrations. A real subprocess probe verified its `NSBundle.main`
  is `/Applications/Jaeger AI.app`, its ID is `com.jenkinsrobotics.JaegerAI`, and
  it can read `NSCameraUsageDescription`. Merely requesting consent in the
  parent did not fix Qt's missing-metadata check in an external interpreter.
  This is still a repository-backed development install, not a self-contained
  Python distribution. The helper is another executable in the same bundle,
  not a separately registered application or a second agent.
- Added camera-denial, pending-permission, late-camera-off, and hidden-window
  autostart regression checks, plus an Avatar product-name assertion.

An early isolated Qt test invocation passed its assertions but crashed during
pytest garbage collection. The new tests now explicitly schedule Qt widget
deletion and flush deferred deletes before fixture teardown; the focused suite
then exited normally. That intermediate crash is not counted as a passing run.

Rebuilt and installed the updated native bundle. The previous installed bundle
is recoverable at
`.jaeger_os/launcher-backups/8ef2f795889b48968391ea060f8d5bbe/Jaeger AI.app`.
`--verify-launch` passed for the installed 0.12.0 bundle.
The final camera-consent build additionally retained the preceding build at
`.jaeger_os/launcher-backups/1ef0d9be10814922a1c7e15376ac0ea4/Jaeger AI.app`.
The embedded-helper build retained its predecessor at
`.jaeger_os/launcher-backups/88055e0e658245f28de46582ba23e111/Jaeger AI.app`.

### Final packaged-helper live revalidation

- Launched the installed app again, with the benchmark's opt-in lean tool
  surface for this last UI check; no default-instance configuration was changed.
- Opened its embedded helper through the native Multimodal button. It answered
  `BUNDLE-READY` through the actual input/Send controls.
- Closed the helper window; its process exited while the same bridge remained
  alive. Reopened it through the native button with the same bridge PID, without
  another model/speech load. Opening the installed app again also reopened Chat.
- Verified the corrected native Avatar title, **Jaeger AI — Jaeger Dev · Avatar
  + Chat**. Inspected the revised full-width input and wrapped permission text.
- Both native and helper now report `com.jenkinsrobotics.JaegerAI`, valid icons,
  and regular/accessory activation policies respectively. One native Dock owner
  remains even after reopening the helper.
- The final helper log contains no missing `NSCameraUsageDescription` error.
  Camera access still resolves as denied, video stays off, and the UI explains
  how to enable it. No permission database was reset and no permission grant was
  made on the user's behalf. Actual camera frames remain unverified.
- Quit the isolated native app after testing. Final logs:
  `/tmp/jaeger-live-bundled-20260907.stderr.log` and
  `/tmp/jaeger-live-bundled-20260907.stdout.log`.

## Regression verification

| Suite | Result |
| --- | --- |
| Jaeger AI full pytest | 2,713 passed, 10 skipped; 118.83 s |
| Jaeger Agent full pytest | 485 passed; 14.59 s |
| Final native Swift tests | 39 passed, 0 failures |
| Agent portable selftest | 23/23 |
| UI event-routing selftest | 11/11 |
| Installed app launch diagnostic and strict signature verification | Passed |
| Existing environment `pip check` | No broken requirements |
| Changed Python critical-error lint and `git diff --check` | Passed |

Total **3,237 passing suite tests**, plus the two selftests. The full app suite
emitted four dependency warnings (audioop, torch.jit.script, and two Misaki
importlib-resources deprecations); none were test failures. Full-repository
lint debt was not addressed or declared clean.

Commands: `.venv/bin/python -m pytest -q` in JaegerAI;
`../JaegerAI/.venv/bin/python -m pytest -q` in the sibling jaeger-agent;
`JAEGER_BRIDGE_CMD=/usr/bin/false swift test` in `jaeger_ai/interfaces/swift`.
Logs: `/tmp/jaeger-ai-full-20260907.log`, `/tmp/jaeger-agent-full-20260907.log`,
`/tmp/jaeger-swift-final-20260907.log`, and
`/tmp/jaeger-live-install-final-20260907.log`.

## Recorded real-model comparison

The original VoiceLLM scorer independently recalculated correctness from raw
responses. These are single runs, not a three-repetition statistical study.
There was only one benchmark model process at a time. A few short Qt regression
checks overlapped development work during the agentic run, so these remain
development measurements rather than fully controlled performance certification.

| Metric | Original Gemma modular | Jaeger AI chatbot | Jaeger AI agentic |
| --- | ---: | ---: | ---: |
| Correct cases | 19/19 | 19/19 | 19/19 |
| Spoken-input WER | 2.90% | 2.90% | 2.90% |
| Spoken cases producing audio | 12/12 | 12/12 | 7/12 |
| Median spoken first audio | 1.843 s | 1.762 s | 2.032 s |
| Worst spoken first audio | — | 2.185 s | 18.294 s |
| Startup/load boundary | 15.699 s | 28.223 s | 40.571 s |
| Case runtime errors | 0 | 0 | 0 |
| Bridge exit | Clean reference | 0 + protocol bye | 0 + protocol bye |

Agentic median/worst are calculated only across audio-producing spoken cases.
Five cases selected text without speech; they are not missing audio frames.
The scorer's overall audio coverage additionally includes text/image cases;
it is not the spoken-only coverage reported above.

The agentic file workflow executed both `write_file` and `read_file`, verified
the actual `READY-012` contents in the temporary workspace, and passed in
15.923 seconds. Agentic → Chatbot → Agentic retained `ORBIT-CEDAR-712`; returning
to the tool-bearing prompt took 16.21 seconds. Native dictation also decoded the
recorded “What is 2 plus 2?” using the bridge-owned Whisper.

Artifacts:

- [Agentic raw results](../../../benchmark/results/live_verification_20260907/agentic.json)
  and [independent comparison](../../../benchmark/results/live_verification_20260907/agentic_comparison.md).
- [Chatbot raw results](../../../benchmark/results/live_verification_20260907/chatbot.json)
  and [independent comparison](../../../benchmark/results/live_verification_20260907/chatbot_comparison.md).
- Matching `.lifecycle.json` and `.bridge.log` files record shutdown and model
  startup. Console logs are `/tmp/jaeger-agentic-live-20260907.log` and
  `/tmp/jaeger-chatbot-live-20260907.log`.

Reproduce from the JaegerAI repository:

```sh
.venv/bin/python dev/benchmark/attached_multimodal.py \
  --source-instance .jaeger_os/instances/jaeger-dev \
  --benchmark-dir '../VoiceLLM-Playground/Multimodal LLM/benchmark' \
  --audio-dir ../jaeger_agent_omni/research/cases12 \
  --model-path jaeger_ai/models/gemma-4-E4B-it-Q4_K_M.gguf \
  --output dev/benchmark/results/live_verification_20260907/agentic.json \
  --workflow --mode-switch
```

For the chatbot control, use a different output path and replace
`--workflow --mode-switch` with `--no-agentic-tools`. Choose fresh output names
to preserve the recorded run artifacts.

## Release limits remain

The [existing hardening report](MULTIMODAL_HARDENING_20260904.md) still governs
release readiness. This pass does not complete the native/TUI/persona
single-front-door migration, solve cold/vision latency, certify live AEC/barge-in,
test security attacks in an enforced sandbox, or provide Developer ID
signing/notarization and a clean-install release against published dependency
refs. Camera permission and actual camera-frame capture must be verified
separately; successful deterministic image reasoning is not live video testing.

Half-duplex remains the preferred default. Quasi/full duplex remain experimental
until echo, near-end speech, double-talk, device recovery, and busy shutdown have
their own recorded acceptance tests.

## Follow-up: growing preview and missing microphone — 2026-09-07

The operator's live report exposed two UI/device defects that the recorded-input
benchmark could not establish:

- The QLabel preview fed each scaled pixmap back into its layout size hint.
  It now ignores pixmap size as a layout constraint and scales inside its content
  rectangle, so successive frames cannot expand the panel/window.
- Camera capture began while the audio engine was still initializing. On this
  host, camera-first startup caused PortAudio failures. Video now waits for audio
  initialization and the first actual PCM block. Mic unmute and audio-resource
  restart release video before opening input again, then resume requested video.
- `Mic: On` previously described intent, not capture. The face now reports
  waiting, permission, starting, live, muted, error, and no-audio states, alongside
  the device name, captured-block count, and a real dBFS level meter. Silent PCM
  is still valid capture; no incoming frames for five seconds is shown separately.
- A failed stream start now closes the stream even if stopping it raises. If
  native close itself fails, its callback owner is retained until process exit.
  Queued events from old workers cannot change the newly selected session.

These changes are in the application face. They do not replace JaegerAgent's
tools, memory, model, endpointing, transcription, speech synthesis, or turn policy.
Default audio mode remains half-duplex.

### Physical-device verification

The reusable [live capture probe](../../../verification/multimodal_capture.py)
uses the actual window and device methods inside the installed app's bundled
interpreter/privacy identity, with a stub consumer instead of another model.
It saves no audio or images. [Raw results](../../../benchmark/results/live_verification_20260907/device_capture_fixed.json)
contain all phases from four clean process runs:

| Run | Audio blocks | Camera frames | First video after audio block | Result |
|---|---:|---:|---:|---|
| 1 | 314 | 477 | 3 | PASS |
| 2 | 315 | 478 | 3 | PASS |
| 3 | 316 | 478 | 3 | PASS |
| 4 | 315 | 478 | 2 | PASS |

All runs tested initial capture, mic mute/unmute while video was selected,
camera off/on during audio capture, and audio-resource restart. Audio and video
continued together in all measured phases. The preview remained **408×346**
inside a **1760×900** window; all geometry comparisons passed. The microphone
reported **Elgato XLR Dock** and received nonzero samples. All processes exited 0.

The focused headless UI/device suite passed **34 tests**, including repeated
frames, denied/late permission responses, stop/close errors, stale callbacks,
muted startup, and engine-owned quasi/full-duplex telemetry. These hardware runs
verify half-duplex capture and UI lifecycle, not live duplex acoustics or a new
semantic/latency benchmark. The broader release limits above still apply.

Full application suite: **2731 passed, 10 skipped, 4 warnings** (120.16 s),
using `.venv/bin/python -m pytest -q -p no:cacheprovider`. The final explicit
native-close-error handling adjustment was then rechecked with the **34-test**
focused suite and physical run 4. Event-routing selftest: **11/11**.
`git diff --check` and updated local report links also passed. No commit or
release was made; this is local development code.
