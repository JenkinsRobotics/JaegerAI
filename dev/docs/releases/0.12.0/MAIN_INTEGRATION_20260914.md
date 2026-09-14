# 0.12.0 integration with main — 2026-09-14

The saved multimodal work has been rebased onto the collaborator's main branch.
The integration retains the incoming gateway, cognition, onboarding, WebUI,
native desktop, model routing, and vendored package changes. No remote branch
has been pushed and main has not been modified.

## Recovery and provenance

- Original app checkpoint: `8b1f669dcd43ee79df4e7e31d7927a3e6b8bb3bd`.
- Recovery branch: `backup/0.12.0-before-upstream-20260914`.
- Original agent checkpoint: `ef1b11a`, preserved on
  `backup/1.2.0-before-upstream-20260914` in the sibling agent repository.
- Incoming main: `6f1a3d7de58878ee8b4504f22db02c9adcf5bddc`.
- Integration code: `e8a2fb2`, following `5fa5e68`, `164af9c`, `59aa68b`, and `de4876e`.
- Integration checkout: `/tmp/JaegerAI-integration-20260914`.

The app commits were consolidated before rebasing because main had moved to
the monorepo package layout. The original commits remain reachable through
the recovery branch. Main is an ancestor of the resulting integration.

## Integration repairs

Media, tool selection, cancellation, session continuity, and request ownership
now survive both native and attached conversation paths. Attached approvals
route only to the originating connection. Agentic and chatbot modes share
history without losing images or executing a turn twice.

Persona composition preserves quantities and the leading factual assertion.
Private requests keep an already loaded in-process model instead of requiring
an unrelated Ollama service. Neural audio initializes and runs from installed
wheels; the cold-start benchmark now measures initialization with the same
180-second budget as attached audio requests.

The installer builds all five packages from external staging directories.
Native builds and their launchers share an external build location, honor
`JAEGER_VENV`, and use the correct executable and helper entitlements. Signing
errors now fail the build. Installer replacements preserve the previous app. Installed launchers carry
the source checkout and external environment into updates. The updater rebuilds
all five wheels; operator-state overrides cannot become update destinations.

## Verification

Verification ran on an Apple M1 Max with Python 3.11.9. Runtime state, virtual
environments, test caches, build outputs, and benchmark instances were isolated
outside the source checkout. Recorded audio and generated image fixtures were
used for model acceptance; this is not a physical camera/microphone test.

| Check | Result |
| --- | --- |
| Full app suite before the final updater repair | 4,426 passed; 1 skipped |
| Complete CLI suite and resolver checks after updater repair | 291 passed |
| All four vendored package suites | 1,674 passed; 2 skipped |
| Required release smoke suite | 169 passed |
| Swift suite after final native launcher changes | 134 executed; 2 skipped; 0 failures |
| Native release build | Passed; ad-hoc signature verified with deep/strict checks |
| Native `--verify-launch` | Passed; launcher, helper, icon, Dock identity, privacy strings |
| Embedded helper | PySide6 multimedia and multimodal window imports passed |
| Five wheels and source distributions | Built successfully in external staging |
| Fresh installed environment | All packages installed; `pip check` passed |
| Installed agentic multimodal acceptance | 19/19 correct; no errors; 12/12 spoken outputs |
| Installed chatbot multimodal acceptance | 19/19 correct; no errors; 12/12 spoken outputs |
| Native conversation probes | 3/3 passed: remember, recall across tool modes, image |
| Real file workflow | `read_file` and `write_file` observed; exact `READY-012` artifact |
| Mode continuity | Agentic → chatbot → agentic retained the reference code |
| Cancellation | Caller released in 24 ms; following turn returned `AFTER-CANCEL` |
| Complete security scenarios after local routing repair | 15/15 passed; no inconclusive cases |
| OS sandbox enforcement | 4/4 denied: outside read, write, chmod, and network |
| Static checks | Ruff fatal-error rules, shell syntax, diff whitespace, no conflicts |

The two Swift skips are opt-in live dispatcher tests. Cancellation timing is
the caller's release time, not a claim that GPU work terminated in 24 ms.
The first independent installed speech initialization took 36.8 seconds;
subsequent native dictation probes took approximately 16–18 seconds including
speech startup. Median spoken response completion was approximately 4.0 seconds
in agentic mode and 1.75 seconds in chatbot mode for this small local corpus.

The initial security run passed 13/15. The two failures returned empty answers
when private routing attempted an unavailable Ollama service. After repair,
both passed in a dedicated sandboxed rerun and the subsequent complete 15-case
run passed. An earlier targeted rerun exceeded
its deadline while another real-model acceptance run was active; it is not
counted as a pass.

## Evidence and local artifacts

- `/tmp/jaeger-integration-app-tests-final.log`
- `/tmp/jaeger-integration-all-packages-final.log`
- `/tmp/jaeger-integration-smoke-update-final.log`
- `/tmp/jaeger-integration-update-tests.log`
- `/tmp/jaeger-integration-real-update-refresh.log`
- `/tmp/jaeger-integration-swift-update-final.log`
- `/tmp/jaeger-integration-installed-agentic-2.json`
- `/tmp/jaeger-integration-installed-chatbot-final.json`
- `/tmp/jaeger-integration-security-complete.json`
- `/tmp/jaeger-integration-security-routing-2.json`
- `/tmp/jaeger-integration-native-launch-final.json`
- `/tmp/jaeger-integration-native-release-final.log`
- `/tmp/jaeger-integration-dist-final/` — all five wheels and source archives
- `/tmp/jaeger-integration-installed-20260914/` — independent installed environment
- `/tmp/jaeger-integration-swift-build/JaegerAI.app` — local release build

The agentic installed acceptance preceded the final privacy-routing and native
packaging repair. Those changes have dedicated regression tests, real private
request checks, native build checks, and the subsequent full app suite. Chatbot
acceptance used the refreshed app wheel containing those repairs. The final
updater/source-location changes were verified with the complete CLI suite,
resolver tests, Swift suite, and the actual five-package refresh operation.
Model acceptance used Gemma 4 E4B Q4_K_M, its BF16 vision projector, Whisper
large-v3-turbo, and Kokoro af_heart. The installed dependency snapshot is in
`/tmp/jaeger-integration-installed-requirements.txt`.

## Release boundary

The artifacts are suitable for local integration review. Public distribution
still requires Developer ID signing and notarization; this Mac reports zero
Developer ID Application identities. The native app references its installed
Python environment and cannot be shipped alone to another Mac. Release builds
also require the configured utility-model and Kokoro caches.

Physical camera/microphone consent, playback, and live dispatcher continuity
remain manual or opt-in release checks. No public release, main push, remote CI
run, or external-provider acceptance is claimed by this report.
