# Desktop launcher and icon verification — 2026-09-04

## Scope and outcome

CPU-only verification requested while another agent uses the GPU. No live
agent, neural model, microphone stream, camera stream, or normal desktop app
session was started in this pass. This is not a new inference benchmark or
production sign-off.

Installed the rebuilt native Jaeger AI 0.12.0 bundle at
`/Applications/Jaeger AI.app` and registered it with LaunchServices. The repo's
`Jaeger AI.app` link points to the native development build. Normal opening
starts the agent; defer that until GPU resources are available.

## Fixes

- Centralized Qt application/window identity in
  `interfaces/pyside6/branding.py`. Chat, avatar, settings, tray, and multimodal
  entry points use the existing 1024px transparent desktop icon, not a tray
  glyph or an unbranded Python default.
- The native app owns the regular Dock/Cmd-Tab entry. Its attached multimodal
  Qt helper receives `JAEGER_DESKTOP_HELPER=1` and uses macOS accessory policy
  while retaining the same icon. Standalone Qt faces retain a branded entry.
- Native Dock reopen shows the shared chat window. Closing windows does not
  terminate the shared agent.
- Replaced the installed thin shell launcher with the native bundle. Installer
  validates product identity, stages a copy, preserves the old bundle, and
  restores it if the final rename fails.
- Build stamps the actual repository launcher path into the signed bundle;
  installed apps no longer depend on the old `GITHUB/JROS` fallback.
- Added camera privacy metadata alongside the existing microphone description.
  No permission prompt or device capture was exercised.
- Added native executable `--verify-launch`: checks bundle identity, version,
  icon, launcher path, Dock configuration, and privacy metadata, then exits
  before creating NSApplication or starting the agent.

Native and installed `AppIcon.icns` SHA-256:
`12bd8988919ad849d789f931f514637d0eb106bda602b71dd97383411a83c661`.

## Verification results

| Check | Result |
| --- | --- |
| Jaeger AI launcher, branding, popup, bridge, attached-runtime tests | 98 passed, 12.84 s |
| Jaeger Agent turn, cancellation, output, context, multimodal, speech, vision-routing tests | 106 passed, 2.23 s |
| Native Swift tests | 36 passed, 0 failures |
| Native development bundle build | Passed |
| Installed executable `--verify-launch` | `ok: true`, version `0.12.0` |
| Installed bundle strict signature verification and plist lint | Passed |
| New helper/guard/launcher/identity-test Ruff checks | Passed |
| `git diff --check` | Passed |

Total: **240 targeted tests passed**. These are selected regression suites,
not a claim that the entire repository suite was rerun in this pass.

Chat and multimodal windows were constructed, displayed offscreen, rendered
with QPainter into QImage, and visually inspected. The multimodal test stubs
session startup, camera discovery, and camera activation. Both share the
application's icon. The multimodal view displays half-duplex and agentic mode.
Dock suppression is covered by a mocked AppKit policy test, not a live Dock
observation.

The opt-in `dev/verification/cpu_only/sitecustomize.py` sets Qt software/offscreen
rendering and rejects real imports of neural backends including llama.cpp,
MLX, PyTorch, Kokoro, and Whisper. It applies only to commands using the
explicit PYTHONPATH, including their Python subprocesses; other agents are
unaffected. Swift tests use a disabled bridge executable.

## Reproduce without starting the agent

From the JaegerAI repository:

```sh
PYTHONPATH="$PWD/dev/verification/cpu_only:$PWD" .venv/bin/python -m pytest -q \
  dev/tests/jaeger_ai/cli/verbs/test_launcher_verb.py \
  dev/tests/jaeger_ai/interfaces/test_product_branding.py \
  dev/tests/jaeger_ai/interfaces/test_desktop_identity.py \
  dev/tests/jaeger_ai/interfaces/pyside6/test_multimodal.py \
  dev/tests/jaeger_ai/interfaces/test_settings_window.py \
  dev/tests/jaeger_ai/interfaces/test_bridge.py \
  dev/tests/jaeger_ai/interfaces/test_attached_multimodal.py \
  -W error::pytest.PytestUnhandledThreadExceptionWarning
```

Installed-app diagnostics:

```sh
"/Applications/Jaeger AI.app/Contents/MacOS/JaegerOS" --verify-launch
codesign --verify --deep --strict "/Applications/Jaeger AI.app"
plutil -lint "/Applications/Jaeger AI.app/Contents/Info.plist"
```

From `jaeger_ai/interfaces/swift`:

```sh
JAEGER_BRIDGE_CMD=/usr/bin/false swift test
```

From the sibling `jaeger-agent` repository:

```sh
PYTHONPATH='/Users/jonathanjenkins/GITHUB/JaegerAI/dev/verification/cpu_only:/Users/jonathanjenkins/GITHUB/JaegerAI' \
  /Users/jonathanjenkins/GITHUB/JaegerAI/.venv/bin/python -m pytest -q \
  tests/test_run_turn.py tests/test_turn_cancellation.py tests/test_outputs.py \
  tests/test_context_guard.py tests/test_turn_transcript_safety.py \
  tests/test_multimodal.py tests/test_speech_runtime.py tests/test_vision_routing.py
```

Raw local logs: `/tmp/jaeger-desktop-cpu-final.log`,
`/tmp/jaeger-agent-desktop-cpu-tests.log`,
`/tmp/jaeger-desktop-swift-final.log`,
`/tmp/jaeger-desktop-render-tests.log`, and
`/tmp/jaeger-desktop-install-final.log`.

## Recoverability and remaining live checks

Original thin launcher retained at:
`.jaeger_os/launcher-backups/79a2e95a49014fdfb67dc42c7873e5c5/Jaeger AI.app`.
An intermediate native build was also retained at:
`.jaeger_os/launcher-backups/0cb47a82b2dc47f9b769093e008d06f5/Jaeger AI.app`.
No user instance, memory, configuration, or model data was removed.

When the GPU is free, open the installed app and verify the Dock/Launchpad
appearance, window focus/reopen behavior, permissions, and live multimodal
session startup. This build is locally ad-hoc signed, not a notarized release.
Earlier production-review blockers remain separate from this desktop pass.
