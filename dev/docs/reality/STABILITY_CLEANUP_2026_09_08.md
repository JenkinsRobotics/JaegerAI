# Stack stability cleanup — 2026-09-08

## Scope

Stabilize the existing shared Hermes WebUI deployment while preserving independent
Hermes, OpenClaw, and Jaeger agents, Jaeger delegation, and Roundtable. This pass
targets lifecycle/recovery defects and obsolete launch configuration; it does not
replace the agent frameworks or migrate conversations.

The working tree already contained lifecycle, dispatch, host-service and supervisor
changes. Those were preserved and backed up before this pass. The lifecycle module
was refactored on top of that work, rather than discarded.

## Fixed

- `restart --dry-run` previously discarded the preview flag and could execute a
  real restart. Preview now propagates to both phases; unknown flags are rejected
  before shutdown begins.
- `start` previously booted out loaded services before bootstrapping them. It now
  preserves running processes, starts missing workers without force, and starts
  containers before services that execute inside them.
- `stop` previously ignored failed launchd commands and still reported success.
  Failure now returns nonzero and blocks the subsequent restart. Failure to stop
  the watchdog halts shutdown before touching other workers.
- Lifecycle operations now use deployment-selected container identities instead
  of hardcoded managed names. Inspection and subprocess calls have bounded waits.
  Failed launchd inspection prevents lifecycle mutations.
- The status table no longer treats the legacy webhook listener on port 8791 as
  proof that Jaeger's Unix-socket bridge is ready.
- Automatic recovery no longer uses forced launchd restarts on a live worker.
  It preserves healthy Jaeger/A2A/OpenClaw dependencies when another component
  fails, and can recover a missing adapter without restarting its healthy agent.
- Live verification scripts now preserve configured model defaults unless an
  explicit `--model` is supplied, removing their fixed dependency on the old rack
  model selection.
- CI now checks that the pinned WebUI plus Jaeger overlay assembles and that the
  resulting Python modules compile. This is an assembly check, not a substitute
  for browser/end-to-end compatibility testing.

## Local cleanup

Four disabled, unloaded legacy ARES launch-agent files were moved from
`~/Library/LaunchAgents` into a private Desktop archive with a restore manifest:

- `com.jenkinsrobotics.ares-containers.plist`
- `com.jenkinsrobotics.ares-control.plist`
- `com.jenkinsrobotics.ares-tailproxy.plist`
- `com.jenkinsrobotics.ares-tailproxy-jaeger.plist`

The archive is `~/Desktop/JaegerAI-Archive-20260908-230839`. It also contains
pre-cleanup source snapshots, the pre-existing tracked diff, and restore notes.
The old container launcher names retired containers that share ports/state with
the replacements. It was already disabled; archiving it removes an obsolete
startup entry, not a currently running fault.

Retained deliberately: active sibling repositories, models, agent state,
conversations, ARES host-tool dependencies, stopped rollback containers, build
artifacts of uncertain use, and Desktop GitHub shortcuts. The shortcuts point
to the canonical repos; they are not duplicate stacks.

## Deployment and verification

- All six configured watchdog component probes passed before reloading it.
- Only the watchdog was reloaded to pick up recovery changes. Existing agent
  services and containers were not restarted by this cleanup.
- Full root regression: **3,778 passed, 11 skipped**, with an existing `audioop`
  deprecation warning; 234.46 seconds.
- Final focused lifecycle/recovery regression: **35 passed**.
- The unsafe lifecycle behaviors were reproduced by new regression tests before
  the fixes. Tests use isolated state and mocked lifecycle effects.
- The pinned WebUI overlay assembled successfully, all assembled `api` Python
  modules compiled, changed runtime code passed critical static checks, and the
  CI workflow parsed successfully.
- The actual shared WebUI responds on the deployed container/Tailscale address.
  Empty localhost ports 8787/8790 do not imply this shared deployment is offline.
- Real `jaeger start --no-app` returned success with every managed worker PID
  unchanged, including while the Roundtable verification was running.
- All four WebUI profiles passed live two-turn recall with their configured
  model defaults. Verification sessions: Hermes `f6abf74f7d6e`, Jaeger
  `79e11cdb89b9`, OpenClaw `ae6ba93d295d`, Roundtable `d09ba5e2c0dd`.
  The Roundtable check verified each initial member's answer rather than counting
  the echoed user prompt as evidence; its follow-up targeted Jaeger and passed.
  Roundtable completed in 90.1 seconds across both turns during concurrent tests;
  this establishes functionality, not a latency guarantee.
- Jaeger session `51413393fcd9` emitted live `read_file` start/completion events
  and returned the correct first line of the repository README in 18.33 seconds.
  No approval was requested by that read, so this is not live approval-relay
  certification. Clearly labeled verification conversations were added.

## Remaining boundaries

Passing health probes proves endpoint availability, not unlimited autonomous
execution. Native OpenClaw approvals, Roundtable control/recovery parity, and
upstream patch retirement retain the gates documented in the integration notes.
The separate standalone Jaeger WebUI path is not the active shared deployment;
its documented adapter port conflicts with the live legacy webhook listener and
requires a deliberate port migration before enabling that additional surface.

No repositories, model files, or conversation databases were deleted. No donor
source or model/provider configuration was changed. No commits or pushes were
made. See `UPSTREAM_INTEGRATION_AUDIT_2026_09_08.md` for the longer-term plan to
consolidate WebUI integration paths and reduce private upstream overrides.
