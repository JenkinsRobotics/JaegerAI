# Legacy frontend cleanup — 2026-10-19

Current authorization: archive all superseded frontend implementations. No running process migration, install, restart, permissions/security changes, userdata or credential changes. Sole code owner. This supersedes the earlier decision to retain the whole SwiftUI source for voice dependencies.

## Recoverable archive

`/Users/matthewjenkins/Desktop/JaegerAI-Legacy-Archive-2026-10-19-150651`

`manifest.json`: original/destination paths, source revisions, SHA-256 file hashes and symlink targets. `JaegerAI-history.bundle` and `JaegerAI-before-frontend-removal.bundle`: Git history/refs before each cleanup phase. Metadata preserves dirty/staged patches, untracked source and disconnected worktree administration. Old source is outside the canonical repo; no archived `.git` pointer is active. No history was rewritten. Restore through a reviewed checkout and patches; never blindly restore old pointer files or run archived launchers.

## Removed implementations

- Entire `jaeger_ai/interfaces/swift`: old SwiftUI application, voice/avatar/chat windows, tests, build/install scripts, resources and entitlements.
- Entire `interfaces/pyside6`, `avatar_chat`, `avatar_player`: superseded Qt desktop/chat/avatar presentation and its retired tests; `core/windowed.py` and old Qt app manifests and the device probe that imported their retired window.
- Old Hermes WebUI frontend: `features/webui/static` application assets and old JS overlays in `assets`. Backend login JavaScript remains required by existing authentication. Backend API/proxy, auth, model/audio services, session state and license remain.
- Removed legacy Swift build/freshness helpers, package-data entries, Qt automatic routing, old shell renderer and `/legacy` opt-in. Missing canonical UI build now gives 503, never an old app. `/legacy` gives 404 even with the former enabling variable.
- Previous phase: 14 inactive bundles, 12 inert VSIX packages, eight safely disconnected external worktrees, five historical proof scripts. Installed IDE extensions untouched and not qualified by version number.

Canonical `interfaces/macos-shell` and `interfaces/ui` stay in place; `apps/macos` and `apps/web` alias them. Normal build, update and launcher paths select the shell. The shell pins its build-stamped repo CLI; a missing wrapper fails rather than selecting an installed or scratch CLI. Unbundled development uses only the explicitly configured/default canonical repo. Historical config values `swift`/`pyside6` remain accepted for existing config files; both select the canonical shell, not old implementations.

## Specifically reused components

Already independently ported into `macos-shell`: Apple Speech STT/TTS, microphone recorder, STT contracts, voice catalog, speech text sanitation, audio math, hotkey/status item, stack CLI adapter and lifecycle policy. Provenance remains in `macos-shell/REUSE.md`; old paths there are historical attribution, not imports.

This cleanup extracted only `remote_runtime.py` (attached multimodal socket adapter) and `preflight.py` (model/device diagnostics) into `interfaces/native_multimodal`. No Qt window, tray, application host or alternate runtime owner was copied there. The adapter remains independently testable, but is not wired into the new shell. Diagnostics use existing device libraries. `jaeger multimodal --check` remains available; requesting the retired window fails explicitly.

The pure 17-line turn-duration formatter was retained at `interfaces/ide/media/turn-duration.js` because the IDE symlink previously pointed into the archived WebUI. It is a required utility, not a legacy frontend.

No additional old Swift component is required to compile the new shell. The old `JaegerMultimodal` executable was an embedded Python host plus signing/privacy packaging, not a reusable Swift library. Its original resources/entitlements are archived; none were applied to the new development identity.

## Known unavailable behavior — not completion claims

- Native ambient voice, barge-in, old avatar/orb windows, and camera/video multimodal presentation are absent from the new shell. Shared backend capabilities remain, but a backend or adapter test does not prove frontend integration.
- Legacy public share-page presentation is archived. Its route returns an explicit 503 until a canonical shared-UI implementation exists. Backend share data/API is retained.
- New shell retains its development bundle identity. Production installation and native permission behavior remain unqualified; no permission, identity or signing-policy change was made.
- No visual/functional parity or live-device acceptance is claimed by these cleanup checks.

## Runtime migration — separate scope, no action taken

1. PID **59466** remains at `~/.jaeger/scratch/mac-integration-20261019/swift/JaegerAI.app`; build commit `5f7a0e6af5cfbb9a1357bd55f520393f6e491b3e`, repo environment points to canonical JaegerAI. It was not moved/stopped. It owns the old menu-bar lifecycle relationship; quitting it can affect Gateway continuity. A coordinated migration must account for lease retirement, independently hosted Gateway continuity, new shell development identity and real voice/permission gaps before replacing it.
2. PID **8931** runs `native-panels/dev/tests/fixtures/gateway_contract_worker.py` using isolated state `~/.jaeger/scratch/second-pass-20261019/ui-fixture`, listening on loopback **56061/56062**. Its registered worktree remains in place. Source plus dirty patches now also have a disconnected, read-only Desktop snapshot. Moving/removing that worktree requires separately authorized fixture migration/shutdown with its isolated state preserved.
3. No listener was present on loopback 8790 at final read-only inspection. The canonical shell defaults to that authenticated WebUI backend; a later runtime migration must arrange that backend before visible app acceptance. No service was started here.
4. Production Gateway PID 59577 and all other services remain untouched. No queued/paused worker was resumed.

## Build and verification record

Canonical UI now builds from an external snapshot with matching lockfile dependencies; no `node_modules` or output is generated in source. Prior output is preserved. WebUI serves `~/.cache/jaeger/ui-rebuild-mainscreen/dist` (explicit `JAEGER_WEBUI_UI_DIST` override remains). New shell builds externally under `~/.cache/jaeger/macos-shell`.

Actual shared UI typecheck/theme/Vite/no-mock build passed; native shell build and 56 Core tests passed. Focused launcher, archive absence, backend UI routing and multimodal adapter checks are recorded after final verification below. No build was installed/launched. Existing compiler warnings are not runtime acceptance.

Focused validation: 129 architecture/entrypoint/adapter/UI-routing checks, 65 additional runtime-model/update/branding checks, two launcher/proxy boundary checks, and the theme guard passed. All 174 shared UI tests and 56 shell Core tests passed. Every one of the 293 removed tracked paths was compared byte-for-byte against its pre-removal Git version in the archive; no dangling active source symlink remains. Source fingerprint matches the built canonical shell.

Evidence logs are preserved under the Desktop archive at `metadata/frontend-cleanup-verification/`. The final all-target runner is repeated unchanged after an earlier run finished its checks but hit a shell read-offset error when its script was edited during execution; that earlier runner exit is not claimed as a pass.

Final unchanged `./scripts/verify.sh` completed successfully for **all** targets, including 219 IDE tests, canonical UI routing/absence guards and both owned-Gateway wiring contracts. The source-pinned launcher change separately passed all 56 shell Core tests; installed/system CLI fallback is no longer eligible. No live app acceptance is inferred.
