# Upstream integration audit and proposed architecture

**Date:** 2026-09-08  
**Status:** Proposed architecture; source audit completed  
**Baseline:** JaegerAI `35a3872`, including existing uncommitted work; WebUI `ffec1915`  
**Product requirement:** Support both independent agents in one WebUI and Jaeger delegating to other runtimes.

## Goal

JaegerAI is a complete assistant product built on JaegerOS and JaegerAgent. It
should also integrate independently useful agent products without taking over
their internal implementations. A user can choose Jaeger, Hermes, or OpenClaw
directly, or ask Jaeger to delegate a task. Roundtable adds optional coordination
across those agents. Models, agent runtimes, and collaboration modes are different
choices and should remain distinct in configuration and the UI.

The README and native integration documents already express most of this goal.
The recommended improvement is to consolidate the integration mechanisms and
make ownership explicit, rather than replace the Jaeger framework.

## What is actually installed in the source tree

| Component | Observed integration | Assessment |
|---|---|---|
| JaegerOS / JaegerAgent | First-party packages under `packages/` | Legitimate owned code; not third-party forks to eliminate |
| Hermes WebUI | Git submodule pointing to `JenkinsRobotics/hermes-webui`, branch `jaeger-adapter` | Actual Hermes WebUI source, with a small fork delta |
| Standalone WebUI launch | `scripts/run-jaeger-webui.sh` executes the submodule's `server.py`, selecting `runner-local` | Clear external-runtime boundary; branding already uses extensions |
| Container WebUI build | `scripts/prepare-hermes-webui.py` archives that submodule, applies a patch, copies Python overlays | A second customization layer on top of the fork |
| Hermes Agent | Native API plus Jaeger-owned launcher, subclass and method overrides | Donor files can stay unchanged while private implementation coupling remains |
| OpenClaw | HTTP fallback and opt-in native WebSocket adapter | External protocol integration; native control parity remains gated |
| ARES host capabilities | Launcher imports sibling `ARES/services/controller` and replaces methods | Deployment-specific source dependency, not a self-contained packaged integration |

Sibling repository remotes point to NousResearch/hermes-agent, nesquena/hermes-webui,
and openclaw/openclaw. ARES is a JenkinsRobotics repository. Remote URLs alone do
not prove those checkouts are unmodified; their complete diffs were not audited.

## Findings, ordered by architectural impact

### 1. High: there are two WebUI customization and deployment paths

The native launcher runs the fork directly; the container build adds
`integrations/hermes_webui/upstream.patch` and overlays. A successful test or
fix on one path does not establish equivalent behavior on the other.

The fork has three commits relative to the locally recorded upstream base
`e168b67e`: seven files, 603 insertions and 12 deletions, including tests. These
changes concern Ollama model lanes and routing schedules to Jaeger. This is not
a measurement against today's remote upstream HEAD. The additional overlay is
448 lines and touches 13 files, including runtime loading, routes, profiles,
commands, container setup, frontend code, and a test.

**Recommendation:** maintain one pinned WebUI source and one integration
configuration, usable by native and container launchers. Preserve deployment
options while eliminating divergent application behavior. Keep the fork until
its required capabilities have verified replacements; changing the submodule URL
alone would discard model and scheduler behavior.

### 2. High: clean donor files do not mean an upstream-compatible integration

`jaeger_agent_compat.py` replaces Hermes' private truncation decision method.
`jaeger_hermes_runs.py` subclasses its API adapter, overrides `_create_agent`,
uses `_ensure_session_db`, and replaces `run_conversation`. The ARES launcher
imports source through `sys.path` and replaces client/server methods.

These fixes have concrete purposes, including avoiding repeated answers and
preserving structured session history. Removing them without replacement would
reintroduce known problems. However, upstream private-method changes can break
them even when no donor file has been edited.

**Recommendation:** treat each as a temporary compatibility patch with a pinned
dependency revision, regression case, owner, and removal condition. Submit general
bug fixes upstream when authorized. Prefer native public APIs; where no adequate
API exists, retain one explicit, tested compatibility module rather than spread
overrides across launchers.

### 3. High: supported operations differ across runtimes and paths

`NATIVE_RUNS.md` and `RELEASE_PROGRESS.md` explicitly report incomplete controls,
recovery, model overrides, and native Roundtable UI integration. A common chat
surface is implemented; complete interchangeability is not established.

**Recommendation:** expose a capability description per backend and version:
streaming, tools, approval responses, confirmed cancellation, attachments,
model/workspace overrides, resumption, and schedules. Show controls only when the
selected route supports them. Pin every active run to its backend, native session,
and native run identity. Preserve unknown execution outcomes rather than replaying
potentially mutating work after a disconnect.

### 4. Medium: the deployment still depends on machine-specific ARES machinery

`scripts/run-host-capability-server.py` resolves a sibling ARES source tree;
profile setup includes ARES state paths and fixed deployment addresses. This is
an optional integration limitation, not evidence that the basic Jaeger assistant
cannot run standalone.

**Recommendation:** either consume ARES host tools as a configured service or
extract the reusable host capability server into a versioned first-party package.
Declare this dependency explicitly. Move endpoint and workspace selection into
deployment configuration. Avoid importing a neighboring checkout's private modules.

### 5. Medium: CI does not verify the complete assembled WebUI

`.github/workflows/ci.yml` runs the Python package suites and other checks, but
does not explicitly initialize the WebUI submodule, prepare the overlay, or run
the assembled WebUI integration tests. Root adapter tests are useful but do not
prove compatibility with the frontend/server version actually shipped.

**Recommendation:** add a focused integration job for the pinned WebUI and
overlay, then a scheduled compatibility job against a candidate upstream revision.
Verify session isolation, stream completion/error, approval routing, cancellation,
restart recovery, and capability-driven controls using isolated test state.
Do not automatically upgrade production because a candidate build succeeds.

### 6. Medium: documentation mixes product architecture and deployment history

The primary README emphasizes the standalone Jaeger WebUI; integration documents
describe a shared Hermes-default container and historical staged/live gates.
The JaegerAgent README also describes remaining host seams while `host.py` says
that list is now empty. These differences make the intended boundary harder to
understand and can lead to work being repeated.

**Recommendation:** publish one current component/ownership map and one current
capability matrix. Keep dated deployment receipts as evidence, with explicit
links to the current status, rather than treating historical test totals as
present-day readiness.

## Proposed decision

Use upstream components unchanged wherever their public interfaces satisfy the
required behavior. Keep Jaeger-owned runtime adapters and optional UI extensions
in this repository. Minimize, document, and test the remaining dependency patches.

```text
Hermes WebUI + Jaeger extensions
  ├─ Direct Jaeger profile ── Jaeger runtime
  ├─ Direct Hermes profile ── Hermes runtime
  ├─ Direct OpenClaw profile ── OpenClaw runtime
  └─ Optional Roundtable ── coordination of native member runs

Jaeger runtime ── delegate tools ── external agent runtimes
```

Direct Hermes/OpenClaw chats must not pass through Jaeger's reasoning loop.
Jaeger delegation is an explicit task relationship with its own child-run
tracking. Share protocol clients where semantics match, while keeping direct
conversation sessions separate from delegated-task sessions. Roundtable owns
coordination records; member agents own their execution and native histories.

The WebUI owns presentation and view preferences. Each runtime owns its tools,
permissions, memory, inference, and schedules. Adapters translate protocols and
track routing/control receipts. They should not grow replacement agent loops or
parallel authoritative conversation databases.

## Options and tradeoffs

| Option | Benefit | Cost / limitation |
|---|---|---|
| Keep fork plus container overlay indefinitely | Preserves current custom behavior | Two integration paths and private-API maintenance |
| Remove all modifications immediately | Small dependency delta | Loses required behavior; existing API gaps remain |
| Upstream-first, adapters/extensions, temporary narrow patches | Preserves both requested modes while reducing divergence | Requires capability tests and staged patch retirement |

Recommend the third option. Upstream already documents static JS/CSS extensions
and a runner adapter contract, but its README also acknowledges remaining Hermes
Agent coupling. An entirely unmodified WebUI with full cross-runtime parity is a
target to validate, not a capability established by this audit.

## Implementation sequence

1. Record exact dependency revisions and every customization, including private
   runtime overrides. Add the assembled-WebUI CI gate before changing pins.
2. Define and test the common capability/routing contract for direct profiles and
   delegates. Reuse existing native Runs and ownership code where appropriate.
3. Consolidate native/container integration configuration and source preparation.
   Preserve existing native session mappings and verify both deployment options.
4. Move cosmetic CSS/branding into supported extensions. Check for proper hooks
   before moving command/profile behavior; DOM patching alone is not a stable API.
5. Evaluate each model-picker and scheduler change against upstream capabilities.
   Keep backend ownership correct; upstream general fixes rather than Jaeger-specific
   endpoint assumptions. Retire each patch only after its regression tests pass.
6. Replace sibling ARES source imports with an explicit service/package boundary.
7. Complete native control/recovery tests before enabling currently gated routes.

The first implementation milestone is reproducible dependency assembly and a
truthful capability matrix, not a broad runtime rewrite.

## Verification and limits

- Inspected Jaeger source, dependency metadata, launch/build scripts, integration
  documents, CI, selected runtime adapters, and sibling repository remotes.
- Verified the WebUI submodule has no working-tree modifications.
- Successfully applied `git apply --check` for the container overlay against an
  isolated archive of the currently pinned WebUI using Jaeger's virtualenv Python.
  The system Python could not perform filtered tar extraction; the supported
  virtualenv interpreter completed the check. Temporary archives were removed.
- No live model calls, service restarts, configuration changes, or donor edits.
- No full test suite or browser integration run; existing recorded test counts
  are historical evidence only. Existing uncommitted user work was preserved.

Upstream references checked during this audit:

- [Extension surface](https://github.com/nesquena/hermes-webui/blob/master/docs/EXTENSIONS.md)
- [Runner adapter contract](https://github.com/nesquena/hermes-webui/blob/master/docs/rfcs/hermes-run-adapter-contract.md)
- [Upstream architecture/coupling notes](https://github.com/nesquena/hermes-webui)

These moving upstream references inform the proposal; the locally audited pinned
revision is the implementation baseline.
