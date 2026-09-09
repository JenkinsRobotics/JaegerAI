# JaegerAI completion and operational verification

Completed September 9, 2026, following the September 8 structural audit. The configured desktop and shared WebUI stack is running after a successful managed restart. Hermes, Jaeger, OpenClaw, and Roundtable all processed real conversations. This report describes the checked deployment and its verification limits; it is not a guarantee about every possible provider or hardware configuration.

## Correction after desktop error report

The initial hand-off established WebUI conversations and a running desktop process, but did not establish a working native desktop connection. The operator exposed that gap. The desktop launched a second bridge and received a `locked` fatal response from the existing managed instance.

The desktop now invokes `bridge --attach`; the Python relay connects to the resident instance socket, preserves protocol frames, and treats desktop quit as client disconnect. Explicit Swift instance arguments are now forwarded instead of ignored. The rebuilt app showed `jaeger / Standing by` before the operator requested that screen captures stop. Native chat completion remains unverified; no screenshot or visual automation was used after that instruction.

A second wiring defect hardcoded the native WebUI button to `127.0.0.1:8787` and its health check to an obsolete `8791` endpoint. The button now uses `jaeger webui url`, and the status checks the resolved WebUI address. The current deployment resolves to `http://192.168.64.71:8787/`. Direct HTTP checks of `/`, `/api/profiles`, and `/api/sessions` all returned 200; localhost port 8787 had no listener. The rebuilt app was relaunched and the resolved URL opened.

Focused verification after these changes: 92 Python bridge tests and 56 Swift tests passed; app bundle built and signed; `git diff --check` passed. The managed bridge retained PID 72184 across desktop restarts. This evidence does not establish every native UI or hardware path as complete.

## Repairs

| Area / files | Final behavior and evidence |
| --- | --- |
| `jaeger_ai/interfaces/bridge.py` | Installs a separate permission policy instead of mutating the shared default. This fixes an order-dependent hang where later callers could wait for approval from a closed bridge. The default-provider regression and bridge/SSH suite pass; the full suite also passes with the random seed that exposed the hang. |
| `packages/jaeger-agent/jaeger_agent/memory/sqlite_store.py`, `sqlite_search.py` | Initializes full-text search after the real database schema. Indexes Jaeger's `episodic` user/assistant messages, retains support for the legacy `turns` shape, and synchronizes inserts, updates, and retention deletes. Savepoints avoid committing a caller's transaction. Doctor no longer emits the missing-`turns` warning. |
| `jaeger_ai/core/instance/setup_wizard.py`, memory `sqlite_store.py` | Persists operator name and custom directive in `state.db`, with fact history, without rebinding another active instance. Repeated seeding preserves existing assertions. Replaces the missing `FactsStore` import and swallowed failure. |
| `jaeger_ai/cli/devtools.py`, `jaeger_ai/core/runtime/readiness.py` | Resolves the actual Kokoro player and avatar warm-up modules. |
| `packages/jaeger-os/jaeger_os/nodes/runtime.py`, Kokoro `engine.py` | Passes the configured audio backend into the engine. Environment overrides still work; the standalone engine no longer imports instance modules that moved out of JaegerOS. |
| `packages/jaeger-agent/jaeger_agent/skills/macos_computer_v1/engines/_ax_lowlevel.py` | Uses the installed agent package's dependency resolver for Accessibility, replacing another obsolete import. |
| Whisper `engine/local_agreement/`, `engine/registry.py`, `config.py`, `node.py` | Implements consecutive-decode prefix agreement, stable partial captions, final phrase delivery, reset behavior, and a real growing-window benchmark. The registry forwards model, wake-word, AEC, and audio settings. Non-final captions do not start agent turns. |
| Kokoro `engine.py`, `node.py`, `persistent_player.py` | Lip-sync uses speech PCM instead of a synthetic sine wave. PortAudio telemetry measures output buffers; AVAudio uses a scheduled PCM RMS envelope. Silence and reset behavior are covered. |
| `jaeger_ai/cli/verbs/lifecycle_verbs.py` | Allows up to 30 seconds for service listeners to become ready during cold startup. Starts the desktop after host readiness, preserving the host bridge's ownership. A real host/app restart succeeded with both containers retained. |
| `scripts/hermes-native-api-service.py`, `scripts/run-hermes-native-api.py` | The host launcher adopts an existing healthy native API instead of creating competing servers. Shutdown sends SIGTERM inside the container to the matching user, script, port, and credential-file invocation, avoiding the observed Apple Container exec signal-forwarding failure. Verified by restarting the running service. |
| `jaeger_ai/features/hermes_webui/service.py`, `cli/verbs/webui_verb.py` | `jaeger webui url` discovers the shared container's current address; the standalone URL remains the fallback. |
| Tray `macos.py`, `base.py`; CLI `entry.py`, `__init__.py` | Enables working desktop/WebUI actions, uses the active Python interpreter for voice, quotes terminal commands, and avoids passing instance flags to global lifecycle verbs. CLI help lists lifecycle and integration commands. `update --help` preserves the help argument instead of entering the updater. |
| `jaeger.toml`, terminal/tray modules | Removes two disabled chassis factory declarations and their `NotImplementedError` bodies. The reference audit found only the disabled manifest entries. Real terminal and tray entry points remain; the manifest validates. Before-edit snapshots are in the audit scratch directory. |
| `dev/scripts/generate_agent_contract.py`, `jaeger_ai/docs/agent_contract.md` | Generates documentation from the current framework prompt, Three Laws document, and toolset notes, replacing stale missing-section output. |
| `packages/jaeger-os/pyproject.toml` | Uses explicit source lookup and pytest importlib mode so test directories do not shadow the real framework package. |
| Regression tests | Adds memory synchronization, setup isolation, audio/backend, stable-caption, Accessibility, bridge-policy, container lifecycle, browser-address, and CLI routing checks. The deterministic avatar renderer tests now run by default against the documented LED-style design rather than an obsolete navy backdrop. |

Six stale internal import references were repaired. The remaining dynamic compatibility exports were checked against their actual runtime modules. Abstract interfaces remain typing/extension contracts.

## Verification

| Check | Result |
| --- | --- |
| Python compilation across `jaeger_ai/` and `packages/` | 831 files passed; both changed native API launchers also compiled. |
| Full root `.venv/bin/pytest` | **3,805 passed, 1 skipped, 1 warning**, 113.74 seconds; exit 0. |
| Reproduction settings for final full run | `PYTEST_ADDOPTS='--randomly-seed=3450020131 -o faulthandler_timeout=30'`; no test selection or exclusion flags. |
| Agent package suite | 848 passed. |
| JaegerOS package suite | 279 passed. |
| Kokoro / Whisper package suites | 7 / 6 passed; combined voice package checks also passed after voice changes. |
| Native Swift | Built successfully; 56 tests passed. |
| Critical Ruff checks | `ruff check --select E9,F63,F7,F82 .` passed. |
| Installed dependency consistency | `python -m pip check`: no broken requirements. |
| Packaging | All five projects built as wheels and source archives in an isolated source copy. All ten artifacts passed the release inspector. Extracted-wheel package imports, bridge/terminal imports, the console entry point, and discovery of all five module slots passed. |
| Hermes WebUI assembly | Pinned submodule plus Jaeger overlay assembled; staged API Python compiled. Vendor checkout remains clean. |
| Operator commands | `./jaeger --help`, `./jaeger update --help`, `./jaeger doctor`, `./jaeger status`, and `./jaeger webui url` passed. |
| Operational restart | `./jaeger restart --no-containers` exited 0. Desktop, all nine managed host services, both containers, and Ollama were running/reachable afterward. |
| Git hygiene | `git diff --check` passed. Existing edits and the user's already-staged reference-image deletions were preserved; this pass staged no changes and created no commit. |

The single skip is `test_uppercase_wins_when_both_exist`: this Mac's case-insensitive filesystem cannot hold separate `SOUL.md` and `soul.md` files. The warning is Discord's use of Python's deprecated `audioop` module; the supported Python range remains below 3.13. Doctor itself reports no failed preflight checks or FTS initialization warning.

## Real execution evidence

Final shared UI: `http://192.168.64.71:8787/`. Use `./jaeger webui url` because container addresses can change.

| Profile | Session | Two-turn elapsed | Result |
| --- | --- | --- | --- |
| Hermes (`default`) | `97b6e9c03889` | 6.9 s | Responded, retained the check word in conversation, and saved the transcript. |
| Jaeger | `d38f26fb6476` | 29.3 s | Same checks passed. |
| OpenClaw | `21ffaa55a2f8` | 6.6 s | Same checks passed. |
| Roundtable | `30bfcb1d82c1` | 51.1 s | Initial participant answers validated; the following directed Jaeger turn retained the check word. |

Real file-tool session `1e8e37388285` completed in 18.39 seconds, emitted tool events, called `read_file`, and returned the repository's actual README first line:

```text
<h1 align="center">JaegerAI</h1>
```

Offline voice verification used cached Kokoro and Whisper models. Kokoro synthesized “The garden has seven purple flowers.” LocalAgreement transcribed it exactly, produced stable partial captions, and reported a word-error rate of 0.0 for this short sample. No fake production response or replacement model was used.

Physical microphone capture, speaker acoustics, and robot motion were not exercised. The file-reading probe required no approval, so manual approval-button interaction is not claimed as live-tested. The optional rack Honcho service remains intentionally paused. These limits do not prevent the verified shared WebUI conversations.

## Operation and audit files

From the repository:

```sh
./jaeger start
open "$(./jaeger webui url)"
```

`./jaeger status` checks the fabric. `./jaeger restart --no-containers` reloads managed host services and the desktop while retaining the containers. The current stack already has the repaired host code loaded.

Detailed local logs, build artifacts, and before-edit snapshots are under `/tmp/jaeger-completion-audit/`. Final evidence includes `pytest-complete.log`, `restart-owned-bridge.log`, `status-operational.log`, `doctor-operational.log`, `live-final.log`, `live-tool-final.log`, and `voice-live.log`. This scratch location is temporary; the results above are retained in this report.

The earlier ownership and structural reports remain in this directory: `UPSTREAM_INTEGRATION_AUDIT_2026_09_08.md`, `REPOSITORY_TRIAGE_2026_09_08.md`, and `STABILITY_CLEANUP_2026_09_08.md`. This completion pass made no additional repository-file deletions, dependency upgrades, upstream checkout edits, or credential changes.
