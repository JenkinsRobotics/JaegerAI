# JaegerAI 0.12.0 / JaegerAgent 1.2.0 release-readiness report

Date: 2026-09-03

## Result

The local JaegerAI 0.12.0 / JaegerAgent 1.2.0 development stack is installable
and launchable. JaegerAI is
the application, JaegerOS is its application/runtime framework, and
JaegerAgent is the reusable multimodal agentic mind. The local editable install
has a registered Finder/Spotlight launcher at `/Applications/Jaeger AI.app`
and a clickable signed build at the JaegerAI repository root.

This checkout is ready for local use and release-candidate testing. Public
distribution is not yet releasable because the dependency manifest references
`jaeger-agent@1.2.0`, while the remote jaeger-agent repository has no `1.2.0`
branch or tag. The macOS bundle is ad-hoc signed and therefore also needs a
Developer ID signature/notarization for distribution outside the development
machine.

## Architecture and state ownership

- JaegerAI boots one application instance from
  `.jaeger_os/instances/<name>/` and injects that layout into JaegerAgent.
- `jaeger_agent/core/workspace.py:42` binds workspace paths and the memory
  facade to the host layout. `tests/test_default_workspace.py:36` now verifies
  that a host bind selects `<instance>/memory/state.db` and does not create the
  standalone fallback.
- `jaeger-agent/.jaeger_agent/` is a direct-run fallback workspace, not a
  second JaegerAI instance registry. It was preserved because its database
  contains user state (4 current facts and 8 fact-history rows).
- The package root is clean: only `__init__.py`, `__main__.py`, and
  `module.yaml` are files at `jaeger_agent/`; implementation lives in
  `core/`, with the six capability nodes in `nodes/`.
- The exact legacy multimodal package import path has zero matches in the
  jaeger-agent repository.

## Release fixes made during the audit

- `dev/scripts/run_tests.sh`: corrected repository/venv resolution and made
  the documented four-worker test mode actually use xdist.
- `install.sh:102-187`: development sibling checkouts are resolver overrides,
  and jaeger-agent is installed with `multimodal-duplex`.
- `jaeger_agent/memory/sqlite_store.py:60-119,462-492`: SQLite now uses one
  connection per thread instead of concurrently sharing one connection.
- `jaeger_ai/core/runtime/process_slot.py:43,178`: process-slot claims are
  serialized so two simultaneous launches cannot both acquire the instance.
- `jaeger_os/core/modules.py:335-352`: JaegerOS resolves application modules
  independently from the mind slot; JaegerAI registers itself as the app.
- `jaeger_os/core/safety/permissions.py:500`: confirmation providers no longer
  mutate the global default-policy sentinel, eliminating shutdown stalls.
- `jaeger_ai/interfaces/bridge.py:774-775,1038`: embedded bridge tests return
  normally; only a real CLI-owned Whisper process may use hard process exit.
- `jaeger_ai/interfaces/pyside6/multimodal/preflight.py:23`: mic/camera probes
  are bounded subprocesses and cannot hang the launcher.
- `jaeger_ai/interfaces/pyside6/multimodal/window.py`: camera enumeration is
  asynchronous, so opening the multimodal window cannot block indefinitely.
- `jaeger_ai/personality/`: all 15 bundled personalities are now portable
  `character/v1` packs using the Mochi/JaegerAnimation identity, provenance,
  typed-asset, and render fields. Jaeger-only traits and progression remain
  additive extensions, and the loader retains compatibility with legacy `id`
  plus flat asset entries.
- `jaeger_ai/cli/verbs/launcher_verb.py:22-146`: the installed launcher is now
  `Jaeger AI.app`, carries the product icon, and removes the legacy launcher on
  uninstall.
- `jaeger_ai/interfaces/swift/Scripts/build-app.sh:207`: the repository-root
  clickable app is exposed as `Jaeger AI.app`; its bundle name and identifier
  are now product-correct.
- `scripts/install.sh`: the default product home is now `~/JaegerAI`. A
  legacy `~/jaeger` state root is copied through a temporary staging directory
  and atomically installed only while the legacy app is stopped; the source is
  retained for rollback and interrupted migrations are resumable.
- `install.sh`: product installs now create or refresh the Applications /
  Launchpad entry automatically instead of requiring a follow-up command.
- `jaeger_ai/main.py`: product launch output and log naming now say Jaeger AI,
  and the launcher no longer prefers a stale `/Applications/JaegerOS.app`.
- `pyproject.toml` in both repositories excludes bytecode/build caches, and
  JaegerAI explicitly excludes local model weights. This prevents a local GGUF
  symlink from expanding a wheel build to approximately 37 GB.

## Verification outputs

### Python and Swift suites

- JaegerAI canonical all-tier command:
  `dev/scripts/run_tests.sh --all -- --timeout=60 --timeout-method=thread`
  -> **2674 passed, 10 skipped** in 34.51 s on the final tree. The new tests
  execute legacy-home migration, its live-process safety gate, product-vs-
  development update routing, and character-pack compatibility.
- JaegerAgent full suite:
  `python -m pytest -q --timeout=60 --timeout-method=thread`
  -> **468 passed** in 15.37 s on the final tree.
- JaegerOS full suite:
  `python -m pytest -q -n 4 --timeout=60 --timeout-method=thread`
  -> **561 passed** in 43.46 s.
- Native application suite: `swift test` -> **35 passed**. Its nine stale
  protocol tests now resolve the canonical fixture from the JaegerOS sibling
  checkout or active virtualenv.
- Multimodal file-mode selftest: **23/23**.
- JaegerAI multimodal integration selftest: **11/11**.
- JaegerAgent selfcheck: **19/19**, with 97 tools, 107 recipe skills, and a
  39-tool default bundle.
- `pip check` -> **No broken requirements found**.
- `git diff --check` -> clean in JaegerAI, JaegerAgent, and JaegerOS.

The Python/Swift suite total is **3738 passed, 10 skipped** across JaegerAI,
JaegerAgent, JaegerOS, and Swift. In addition, the two explicit multimodal
selftest commands passed 23 and 11 contract checks, and Agent selfcheck passed
19 checks; focused reruns are not double-counted.

### Package contents

- JaegerAI wheel and sdist build successfully at 39 MB each. Both contain zero
  `.pyc`, zero local neural weights, and zero Swift `.build` entries. The wheel
  contains the application core and multimodal GUI. A fresh 0.12.0 wheel check
  also found all **15** character manifests, all **15** card images, and the
  personality format guide.
- JaegerAnimation's strict `character/v1` loader accepted **15/15** bundled
  Jaeger AI packs, proving they can cross the app boundary without conversion.
- JaegerAgent wheel is 3.0 MB and sdist is 2.6 MB. Both ship all **6**
  `node.json` manifests and **107** `SKILL.md` recipes with zero `.pyc` files.
- An isolated import directly from the built JaegerAgent wheel succeeds while
  pyaec, Kokoro, and pywhispercpp are actively blocked; none are imported.
- Base metadata keeps neural audio packages out of required dependencies;
  `multimodal-duplex` declares the complete optional stack including pyaec.

### Runtime and launch

- `./install.sh` with development siblings completed successfully.
- `./jaeger --doctor --doctor-check` reports all dependencies present and the
  Jaeger fully operational. The only system advisory is optional Full Disk
  Access for protected folders.
- The native bundle builds and passes `codesign --verify --deep --strict`.
- `./jaeger launcher install` installed and registered
  `/Applications/Jaeger AI.app`, including `AppIcon.icns`.
- Opening the installed launcher successfully started the current checkout's
  Swift executable and bridge path.
- The built and launched bundle reports `CFBundleDisplayName=Jaeger AI`,
  `CFBundleIdentifier=com.jenkinsrobotics.JaegerAI`, and version **0.12.0**;
  `codesign --verify --deep --strict` passes.
- Full-duplex multimodal preflight passed **7/9**: engine, AEC, VAD, vision
  projector, Whisper model, Gemma model, and runtime passed. Direct terminal
  microphone and camera probes hit their 8-second timeouts. The broader doctor
  independently reports AVAudioEngine ready plus Accessibility and Screen
  Recording granted. Hardware should be rechecked from the signed app context
  because macOS TCC permissions attach to the launching bundle.

### Benchmark evidence

The existing same-day end-to-end report remains at
`jaeger-agent/benchmark_results/AGENTIC_MULTIMODAL_E2E_20260903.md`:

- VoiceLLM-derived multimodal suite: **19/19**, spoken WER **2.90%**.
- Agent routing: **80/81**.
- Scoped agent scenarios: **38/51**.
- Security checks: **14/15**.

Those imperfect agentic scores are model/task quality work, not regressions in
the imported multimodal transport. They should not be represented as a 100%
production-quality agent benchmark.

## Cleanup performed

Removed generated `__pycache__`, `.pyc`, `.pytest_cache`, `.ruff_cache`,
top-level `build/`, egg metadata, and `.DS_Store` files from both repositories
(about 52 MB after the temporary 37 GB failed package staging tree had already
been removed). Preserved the development virtualenv, model symlinks, signed
Swift build, live JaegerAI instances, standalone agent memory, skill corpus,
tests, docs, and benchmark evidence.

## Remaining release gates

1. Commit and publish the coordinated JaegerAI 0.12.0 and JaegerAgent 1.2.0
   branches/tags. In particular, `JenkinsRobotics/jaeger-agent` must expose a
   `1.2.0` ref before JaegerAI's public dependency install can resolve.
2. Replace moving `master` dependencies with immutable tested release refs.
3. Run mic/camera preflight from the launched app and confirm the TCC prompts.
4. Sign with a Developer ID and notarize/staple the distributable app. The
   current ad-hoc signature is correct for local development but `spctl`
   rejects it for public distribution.
5. Decide whether the release requires a zero-lint gate. Current full-repo
   Ruff `F` scans still report historical unused-import/redundant-string debt
   and dynamic names in an imported red-team recipe, despite all executable
   suites passing.

## Launch commands

```bash
# Finder / Spotlight / Launchpad
open -a "Jaeger AI"

# Main application from the checkout
./jaeger

# Dedicated multimodal face
./jaeger multimodal --audio full

# Recreate the Applications launcher if the checkout moves
./jaeger launcher install
```
