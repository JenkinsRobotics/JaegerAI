# Scoped legacy cleanup — 2026-10-19

Current instruction: cleanup only, one code owner. No feature work, service
restart, worker resume, credential change, or permanent data deletion.

Canonical paths remain `jaeger_ai/interfaces/macos-shell` (native host) and
`jaeger_ai/interfaces/ui` (shared frontend). `apps/macos` and `apps/web` now alias
those paths. The new shell's Package.swift imports only its own Core target;
REUSE.md records the already ported pieces and the deliberately deferred pieces.

## Recovery archive

`/Users/matthewjenkins/Desktop/JaegerAI-Legacy-Archive-2026-10-19-150651`

`manifest.json` records original/destination paths, content hashes, revisions,
protected running bundles, and worktree dispositions. `JaegerAI-history.bundle`
contains the repository refs/history and was verified with `git bundle verify`.
`metadata/` preserves staged/unstaged binary patches, untracked files and worktree
administration. `snapshots/` contains the retained legacy Swift source before edits.
Nothing in the archive is an active linked worktree. Do not run its archived
launchers or source; restore explicitly into a new reviewed location if needed.

## Disposition and evidence

| Item | Evidence / action |
| --- | --- |
| Eight inactive external worktrees | `git worktree move` used first; HEAD checked, Git administration/changes preserved, pointer archived, then only the expected missing-pointer registrations pruned. Archived trees have no `.git` pointer. |
| Inactive Mac bundles | Relocated, with per-file SHA-256 verification. Running bundle excluded. No installed/running app was replaced. |
| Inert old VSIX packages | Archived from scratch directories; final clean 0.1.6 package retained. Installed extensions untouched; version 0.2.0 is not presumed working. |
| Historical `try-typing.sh`, `snapshot.sh`, `verify-input-live.sh` | Archived from the newer shell's Scripts directory. They pin old worktree revisions or write screenshots inside source; current build/live entrypoints retained. |
| Automatic Mac selection/build | Main, agent-create, dev, update and lifecycle launch lookup select only the canonical JaegerShell target. Old installed JaegerAI.app locations are no longer automatic fallbacks. |
| Build output | New shell and script-only Jaeger Dev launcher share one external build root: `~/.cache/jaeger/macos-shell`, overridden by validated `JAEGER_MAC_BUILD`. Running shell replacement is refused; previous builds are moved aside rather than erased. |
| Native production install | Explicitly deferred. New shell currently uses a development bundle identity. Cleanup must not install the old SwiftUI product or silently substitute a new security identity. |

## Retained blockers — do not remove or launch automatically

1. `jaeger_ai/interfaces/swift` remains in source, with a full Desktop snapshot.
   The old app's build also owns the embedded `JaegerMultimodal` host/privacy
   resources; newer shell REUSE.md defers ambient voice/barge-in and the
   AgentBridge-bound speech path. Removing it now would strand still-required
   behavior. Porting/retiring that behavior is separate feature scope. Ordinary
   launch/install/update paths no longer select this target.
2. `jaeger_ai/features/webui` remains required. Shared UI Vite configuration routes
   `/v1` and `/api` through its authenticated proxy; backend routes also own existing
   scheduler/board integrations. Do not remove this backend as an old frontend.
3. Running legacy Mac app PID 59466:
   `~/.jaeger/scratch/mac-integration-20261019/swift/JaegerAI.app`.
   It was not moved/stopped. Its existing lifecycle lease affects the Gateway;
   migration requires separately coordinated app/service scope.
4. Worktree `~/Documents/Codex/2026-10-19/task-3/native-panels` remains registered:
   a running isolated Gateway references it. It was not moved or stopped.
5. Installed VS Code/Antigravity Jaeger extensions remain in place. Their hosts
   are running and profile selections differ. Cleanup does not prove which
   version is loaded, change profiles, or grant a reload/restart.

The prior Mac completion/assessment effort is superseded by this cleanup scope.
No current app-feature completion or visual/function parity is claimed.

## Restore

Use `manifest.json` to locate a relocated bundle/file and move it back only after
checking the destination and active processes. For a worktree, create a new
reviewed checkout at its recorded HEAD from `JaegerAI-history.bundle`; use its
staged/unstaged patches and archived file tree to recover uncommitted work. Do not
copy old `.git` pointer files back blindly. Git history has not been rewritten.

## Validation

Focused launch/update/install selection tests and newer shell Core tests are run
against this change. Build script syntax, external output resolution, archive
hashes, disconnected-worktree state, alias targets, and unchanged running process
identities are checked. Final results are recorded after verification. Canonical
`scripts/verify.sh` is attempted; live-state guard failures are reported rather
than stopping shared services to obtain a green result.

Current focused evidence: 93 Python selection/update/install tests passed; 56
newer-shell Core tests passed; the canonical shell build script completed and
signed its development bundle at the external output path. The bundle was not
launched or installed. The shell compiler emits existing Swift Sendable warnings;
these are not new cleanup features or runtime acceptance evidence.

Archive tally: 14 inactive Mac bundles, 12 inert VSIX packages, five historical
proof scripts and eight disconnected external worktrees, plus preserved alias
records and a legacy Swift source snapshot. Installed IDE versions were not moved.

Final canonical `./scripts/verify.sh` passed all checks, including the WebUI-to-Gateway wiring contract. Nine CI hygiene and six lifecycle checks also passed. The shell launcher now prefers the build-stamped canonical repo wrapper over an installed venv CLI, avoiding stale installed source selection; JAEGER_VENV still selects the wrapper interpreter. No app or service was started or restarted.
