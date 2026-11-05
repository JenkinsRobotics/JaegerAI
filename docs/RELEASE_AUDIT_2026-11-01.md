# JaegerAI release audit and qualification procedure

Classification: CURRENT AUDIT. Audited November 1, 2026 PT (November 2 UTC).
Source: `03094d0cc744dd0bf938a5be3c0baedc34fd2ded`, local `master`.

The release process can currently publish an incomplete, unqualified product.
The principal blockers are distribution assembly, rollback error handling, and
the connection between qualification and publication. This is not evidence that
the entire runtime is broken: real isolated Gateway journeys and the shared UI
component suite work in the checks below.

The existing ten-line `conftest.py` modification was preserved. Wheel builds used
an exported HEAD; UI checks used an external working-source snapshot. No operator
service was restarted, installed application replaced, credentials read, release
published, or remote repository changed. This is a release-engineering audit,
not a comprehensive security assessment or a live cloud-provider certification.

## Confirmed findings

### 1 Publication does not depend on qualification

Priority: release blocker. `.github/workflows/release.yml:18-69` has a single
build-and-publish job with no test step or dependency on successful qualification
of that SHA. Separate CI workflows exist; the publisher does not check their
results. The VSIX commands explicitly tolerate failure (`npm ci || true` and
`package ... || echo ...`). Publication requests `draft: false`,
`prerelease: false`. The manual `version` input is unused, and tag/package version
agreement is not asserted. There is no Mac bundle build in this workflow.

Repair: qualify the exact candidate SHA first; build a required artifact set;
fail if an artifact is absent; verify version and SHA in each artifact; publish
those same immutable bytes. Use a draft release until qualification completes.
Retain the existing Mac bundle identity and permission boundaries.

### 2 Shared UI build and runtime installation do not meet

Priority: release blocker for a fresh WebUI or Mac installation.
`features/webui/api/ui_shell.py:9,36-38` defaults to
`~/.cache/jaeger/ui-rebuild-mainscreen/dist`; an explicit
`JAEGER_WEBUI_UI_DIST` can override it. The release workflow builds into
`interfaces/ui/dist`, then uploads its loose files. Neither `install.sh` nor
`scripts/install.sh` provisions the default external UI build. The update path
does not refresh it either. The external build helper requires pre-provisioned,
lockfile-matching dependencies (`interfaces/ui/scripts/build-external.py`).

The root wheel built from exported HEAD contains 474 UI source members and zero
`interfaces/ui/dist` members. Python package data lists source/public/vendor
paths, not the production dist. A wheel build succeeding is consequently not
proof of a usable installed screen. `StackController.swift:242-243` explicitly
refuses an isolated dev stack when its UI index is absent.

A second wheel build after copying the successful production UI build into the
staged source's `interfaces/ui/dist` still contained zero dist members
(`final-probes.json`). This confirms the packaging omission even when the
frontend has been built first, as in the publishing workflow.

Repair: assemble one versioned shared UI archive, install it to an explicit
resolved external location, wire both clients to it, and include it in updates
and rollback. Prove first launch with an empty user cache; pre-existing developer
builds must not supply missing release content.

### 3 Published root wheel does not declare its Jaeger dependencies

Priority: release blocker for wheel installation. Root wheel metadata contains no
`Requires-Dist` for `jaeger-agent`, `jaeger-os`, or either voice engine.
`requirements.txt` deliberately delegates their installation to the source
installer. `install.sh:107-116` installs all five packages; the release workflow
builds and attaches only the root Python distribution. The CI artifact job builds
five packages, but those artifacts are not handed to the publisher.

Repair: declare package dependency contracts and deliver all required wheels, or
document and enforce a complete source-installer distribution. Do not advertise a
standalone wheel install until a fresh environment resolves the full stack.
Use the same assembled distribution for CI and publication.

### 4 Rollback reports success after dependency restoration fails

Priority: release blocker for safe upgrades.
`cli/verbs/update_verb.py:310-326` ignores `_reinstall_deps(home)`'s return value,
continues rebuilding, deletes `.update-prev`, and returns zero.

Reproduction: a disposable rollback fixture with dependency reinstall forced to
return 37 produced rollback exit 0 and `recovery_copy_retained: false`. Restore
and app-build boundaries were replaced in this narrow error-propagation probe;
no real installed package or operator state was changed.

Repair: propagate failure, retain recoverable previous content, and verify a
coordinated rollback of source, installed packages, UI, app and disposable state.
Also qualify interruption after the updater swaps source but before dependency
installation completes; `_update_download` currently swaps before reinstalling.

### 5 The test environment starter is unsafe as a release harness

Priority: blocker for using this script in qualification.
`scripts/start-test-env.sh` recursively removes the supplied `JAEGER_STATE_DIR`
without validating that it is disposable, uses production ports 33418/8790, and
accepts any successful curl transport as readiness. An existing operator service
could satisfy that check while the new child failed. UI install/build failures
are swallowed. The command `APAecho` near the instance-creation step is invalid
under `set -e`, after the processes have been started. No exit cleanup trap
protects that path. This script was inspected, not executed.

Repair: use a newly allocated external directory, non-production loopback ports,
per-run tokens, PID/endpoint ownership checks, HTTP status assertions and cleanup
of only owned children. Refuse operator/repository paths and symlink escapes.
Do not use this starter against the live installation.

### 6 Test names and summaries overstate coverage

Priority: qualification blocker; not every test is a stub.

| Check | Actual boundary | What it cannot establish |
| --- | --- | --- |
| Hygiene suite | Filesystem names, source-string rules, resolver behavior | Working UI, installed product or live turns |
| WebUI Gateway proxy suite | Replaces `_proxy` and `_proxy_stream` with recording lambdas | HTTP delivery, authentication, SSE delivery or actual Gateway route availability |
| Some interaction-tier tests | Mock `_execute_turn` and model response | Real provider/tool execution |
| Gateway durability suite | Real SQLite, rollback and event replay; some execution paths replaced | Shipped-client or live-provider qualification |
| Owned Gateway process contracts | Real child process, HTTP, EntityRuntime, tools and storage; scripted model | Real cloud model behavior, installed editor, native window |
| Shared UI Vitest suite | Rendered components and substituted API boundaries | Installed browser-to-Gateway-to-provider journey |

`interfaces/ui/tests/e2e/apple-ui.spec.ts:73-82` checks a streaming cursor count
with `toBeGreaterThanOrEqual(0)`: it passes whether streaming works or not. Its
message-response check only requires an assistant element to become visible.
The Playwright config starts Vite, while `.github/workflows/v013-tests.yml` does
not provision the authenticated backend/Gateway for that job. This E2E workflow
was inspected, not executed against a browser in this audit.

Repair: label each suite by its real boundary, remove vacuous assertions, and
verify correlated request IDs, content, terminal state and durable effects in
the assembled installation. Keep deterministic scripted-provider contracts;
add separately reported cloud-provider and actual-client journeys.

### 7 Artifact inspection accepts non-artifacts

Priority: artifact-gate blocker.
`dev/scripts/inspect_release_artifacts.py:32-72` returns an empty member list for
unsupported files and calls them clean unless a filename matches a small set of
required-package prefixes. A directory containing only `release.txt` with
`not an archive` passed with exit 0. All five generated wheels also passed,
despite the missing UI and incomplete root dependency contract above.

Repair: require a declared inventory of archive types, package names and versions;
reject unsupported/empty input; check required runtime assets and dependency
metadata; install and exercise the artifacts. Archive hygiene remains useful,
but is not installation qualification.

### 8 Source launchers and installed dependencies can come from different revisions

Priority: reproducibility blocker.
With the current external venv and ordinary Python import resolution,
`jaeger_ai` resolves to this checkout while `jaeger_agent` and `jaeger_os` resolve
to the venv's site-packages. The `jaeger` wrapper and WebUI launcher prepend only
the root checkout. `dev/scripts/run_tests.sh` and `scripts/verify.sh` prepend
the agent and OS source packages too. Thus a source test pass is not proof of
what a source-launched application does with its installed sibling packages.
Different package versions are legitimate; unrecorded source revisions are the
problem. This probe establishes paths, not that the installed bytes are stale.

Repair: qualify the installed five-package set outside the checkout and retain
package origins, versions, source SHA and content hashes. Compare the same
identity from CLI, Gateway, WebUI, Mac and IDE. Fail on unexpected imports.

### 9 Isolation monitoring cannot attribute writes

Priority: test-credibility repair.
`dev/tests/conftest.py:137-242` compares live-tree file sizes and modification
times before/after a session and blames the tests for any change. It cannot
identify the writing process. It also excludes broad categories including
`memory`, database WAL/SHM files and the main live Gateway store, so absence of a
failure is not proof of no live writes. The earlier hygiene run passed its nine
tests but this monitor failed on worker/job state changes.

Repair: isolate writes at the process/filesystem boundary and report any
remaining live-tree monitoring as unattributed changes. Do not expand ignore
lists merely to turn the gate green; do not treat incidental service activity
as a confirmed product defect.

### 10 The required check set is fragmented

Priority: release-process repair.
`scripts/verify.sh` does not run shared UI Vitest/build, Swift tests, the full
Python unit/package suites, or cloud acceptance. Other workflows cover parts of
these. `v013-tests.yml` is path-filtered and its IDE job runs only controller
tests. `lint.yml` targets main/develop rather than the current master branch;
formatting failure is ignored. The v013 workflow puts Python bytecode under
`${github.workspace}/.cache/pycache`, contrary to the repository's external-cache
rule. The presence of these jobs does not establish current remote CI results.

Repair: define one candidate qualification manifest used by local and CI entry
points. List every selected suite, exit code, skips, timeouts, artifact and
boundary. Publishing must consume this manifest for the exact SHA.

## Executed evidence

Raw logs, probe programs, staged source and artifacts are outside the repository
at `/tmp/jaeger-release-audit-20261102/`. This is disposable local evidence, not a
permanent release attestation. Copy sanitized logs into the candidate's retained
CI artifacts when implementing the release procedure.

| Probe | Result | Scope and evidence file |
| --- | --- | --- |
| Five Python wheels from exported HEAD | All built, no network build isolation | `build-results.json`, individual build logs; installed build tools reused |
| Root wheel member/metadata inspection | No built UI; 474 UI source members; no sibling Jaeger dependencies declared | `root-wheel.json`, wheel `.metadata` files |
| Existing artifact inspector | Five wheels passed; plain text also passed | `inspect.log`; invalid-artifacts fixture |
| Shared UI typecheck | Passed | `ui-typecheck.log` |
| Shared UI component tests | 688 tests in 176 files passed | `ui-vitest.log`; not live backend/provider evidence |
| Shared UI Vite production build | Passed; large-chunk advisory | `ui-build.log`; output `ui-dist/` |
| Theme and production no-mock guards | Both passed | `final-probes.json`; mock mode disabled |
| Root wheel rebuilt after UI build | Built, still omitted compiled UI | `root-with-ui-build.log`, `final-probes.json` |
| IDE Node suite with loopback allowed | Exit 1; 274 passed, 19 failed, 5 skipped, 1 cancelled | `ide-tests-unrestricted.log`; 30-second per-test timeout applied |
| IDE external packaging stage | Passed | `ide-stage.log`; generated contract/build metadata inspected, VSCE install not performed |
| Gateway restart, request replay and SSE | Passed | `runtime-results.json`; scripted provider, real process/runtime/storage |
| Cancel blocked provider then next turn | Passed | `runtime-results.json` |
| Cancel pending approval without effect | Passed | `runtime-results.json` |
| Approved and denied actual file writes | Both passed; exact approved content checked, denied target absent | `runtime-more-results.json` |
| Durable task, verified artifact and restart replay | Passed | `runtime-more-results.json`; real tools/storage, scripted provider |
| Authenticated WebUI proxy to owned Gateway | Passed | `runtime-more-results.json`; real HTTP/login, no browser window |
| Rollback dependency-error propagation | Confirmed false success and discarded recovery copy | `rollback-result.json`; isolated fault injection |
| Required `./scripts/verify.sh` | Exit 1 after nine hygiene tests passed | `verify.log`; unattributed live worker/backlog/job changes; later stages did not run |

Loopback listeners were initially denied by the execution sandbox; those runs
are environmental failures and were rerun with socket access. The successful
Gateway runs used explicit temporary token/state directories and ephemeral
ports. They never contacted an operator listener or real model provider.

The IDE failures include missing/mismatched context, workspace, mention, Plan
mode and startup expectations. Many are source-pattern assertions; this count
does not mean 19 independently reproduced user-facing bugs. The test timeout
also prevents treating this as an unrestricted complete IDE baseline. Diagnose
each against the actual editor behavior before changing either code or tests.

## Repeatable candidate release procedure

This is the procedure to implement after the blockers above are repaired. It is
not a claim that today's scripts already automate all of it.

1. **Freeze the candidate.** Use a clean clone at an exact SHA, preserve the
   operator's dirty checkout, choose the release version, and compare tag,
   Python version, IDE version mapping and Mac build identity. Record toolchain
   versions and dependency resolution. Never attach a newer rebuild to an older
   qualified result.
2. **Build one distribution externally.** Produce all five wheels and sdists,
   the shared UI archive, canonical Mac bundle and staged VSIX. Use the existing
   external staging helpers as starting points. Explicitly connect UI build
   output to runtime configuration. Record a content manifest and SHA-256 for
   every deliverable; require the complete inventory.
3. **Run component and real-process checks.** Record `verify.sh`'s actual result,
   shared UI tests/typecheck/build guards, Swift checks, full selected Python
   tiers and all IDE tests. Separate scripted-provider contracts from cloud
   qualification. Failures need diagnosis; updating assertions or skipping tests
   is not itself a product repair.
4. **Install those artifacts on a fresh profile.** External venv, disposable
   state/cache/workspace, new per-caller tokens, non-production loopback ports.
   Start from outside the source checkout with source `PYTHONPATH` removed.
   Assert package origins and versions. Run the actual supported installer,
   first-launch configuration and UI asset loading; verify missing credentials
   produce a usable setup/error state. Do not borrow the developer's cached UI,
   model configuration, installed packages or editor extension.
5. **Qualify the actual clients and configured cloud provider.** Use the matrix
   below. Correlate UI result, request ID, terminal receipt, event stream and
   independent file/database observations. Record bounded timeouts, errors and
   source/artifact identities. A health response alone is insufficient.
6. **Qualify upgrade and recovery.** Install the previous supported distribution
   in disposable state, create history/settings/tasks, upgrade to the candidate,
   verify continuity, interrupt an update, inject a dependency-install failure,
   and roll back. Confirm source, installed packages, UI and app agree afterward.
   Retain recovery data on failure. Do not test this on operator state.
7. **Create a reviewable draft release.** Attach the exact qualified artifacts,
   checksums, manifest, evidence and limitations. Assert version/SHA agreement,
   complete inventory and signing status. Public Mac delivery requires the
   appropriate distribution signing/notarization path; today's `build-shell.sh`
   explicitly builds debug and signs ad hoc. A developer build is a separate
   delivery claim.
8. **Publish only after candidate acceptance.** Publication and installation into
   the operator's active clients remain separate actions. Verify the downloaded
   bytes match the qualified hashes before the final installed smoke run.

### Existing commands for a candidate checkout

Run from a clean, disposable clone, with `JAEGER_VENV` pointing to a prepared
external environment. These commands collect parts of the evidence; they do
not repair the findings or constitute a publishing command. Preserve each exit
status and full log, and stop on failure. The UI snapshot is outside the clone
so dependency/build output stays out of the source tree.

```bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="${HOME}/.cache/jaeger/pycache"
RELEASE_WORK="$(mktemp -d /tmp/jaeger-candidate.XXXXXXXX)"
JAEGER_PY="${JAEGER_VENV:-${HOME}/.jaeger/venv}/bin/python"

./scripts/verify.sh
./dev/scripts/run_tests.sh --unit
./dev/scripts/run_tests.sh --production-path
./dev/scripts/run_tests.sh --security
./dev/scripts/run_tests.sh --package agent
./dev/scripts/run_tests.sh --package os
./dev/scripts/run_tests.sh --package kokoro
./dev/scripts/run_tests.sh --package whisper

cp -R jaeger_ai/interfaces/ui "$RELEASE_WORK/ui"
npm --prefix "$RELEASE_WORK/ui" ci
npm --prefix "$RELEASE_WORK/ui" test
npm --prefix "$RELEASE_WORK/ui" run build

swift test --package-path jaeger_ai/interfaces/macos-shell \
  --scratch-path "$RELEASE_WORK/swift"
"$JAEGER_PY" -B jaeger_ai/interfaces/ide/package_extension.py \
  --output-root "$RELEASE_WORK/ide"
"$JAEGER_PY" -B scripts/install-packages.py --no-install --sdist \
  --wheel-dir "$RELEASE_WORK/python" \
  packages/jaeger-os packages/jaeger-agent \
  packages/jaeger-kokoro-tts packages/jaeger-whisper-stt .
"$JAEGER_PY" -B dev/scripts/inspect_release_artifacts.py "$RELEASE_WORK/python"
```

Use the complete IDE test invocation in `scripts/verify.sh`, not just the
controller-only CI job. Pass an explicit package name to the package runner.
Reconfirm CLI help if changing the runner. Keep the compiled UI as a coordinated artifact while repairing its
installation path. Do not use `scripts/start-test-env.sh` for the remaining
client/provider acceptance steps until finding 5 is resolved.

## Required behavior matrix

| Journey | Observable acceptance evidence |
| --- | --- |
| Fresh start and identity | Empty-cache install opens; CLI, Gateway and clients expose the candidate identity and expected origins |
| Cloud conversation | Actual configured provider returns correlated text; one durable terminal result and one assistant answer |
| Approved effect | Unique file absent before approval; exact approved bytes present after; receipt agrees with independent file read |
| Denied effect | Denial visible; target unchanged; no delayed/replayed write |
| Task completion | Task reaches verified terminal state; artifact content independently checked; result delivered to originating client |
| Cancellation | In-flight operation reaches one cancelled result; no later side effect; immediate next request works |
| Disconnect and restart | Reconnect resumes ordered events; restart retains transcript/task state; resubmitted request does not repeat effects |
| Client continuity | WebUI and Mac see the same persisted session; IDE uses the same Gateway contract and renders one answer in a real editor |
| Update and rollback | Previous install upgrades with state retained; forced failure reports failure and retains recovery; rollback restores coordinated usable versions |
| Companion behavior | At least one controlled observation → durable task → notification journey; persona/memory continuity checked across restart |

Live cloud, actual browser/native/editor windows, voice hardware, distribution
signing/notarization and the complete upgrade matrix remain unqualified by this
audit. Existing dated release records do not qualify this SHA. No product
feature was removed or silently excluded from the release claim.

## Repair order

1. Make the isolated qualification harness safe and the evidence truthful.
2. Connect shared UI assembly, all package artifacts and installed revision identity.
3. Repair rollback failure handling and qualify interruption recovery.
4. Diagnose the IDE failures; replace vacuous browser checks with correlated results.
5. Require the complete candidate evidence and artifact inventory before publication.

No architectural rewrite is required to begin this sequence. The working
Gateway process contracts provide a useful foundation; extend them through the
installed clients and provider boundary instead of replacing them with another
success-count gate.
