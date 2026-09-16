# JaegerAI Runtime Truth Audit

**Audit date:** 2026-09-15
**Checkout audited:** `main` at `612d6ee3afb1e4f2e59b83d831eddb35d43af1df`
**Scope:** forensic runtime audit only. No refactor, deletion, dependency installation, or architecture change was performed. The only repository file created by this audit is this report.

## Executive verdict

Jaeger is running as a layered system with one primary conversational loop, but several transport and orchestration surfaces. The installed command resolves to this checkout, and the live machine currently has WebUI (`8790`), Gateway (`8810`), Ollama (`11434`), and OpenClaw (`18789`) listeners. The ordinary Jaeger loop is `jaeger_ai.main` → `jaeger-agent`'s `JaegerAgent`/`drive_one_turn` → model adapter → JaegerOS tool registry through the composed tool executor.

The WebUI is a vendored Hermes surface and a protocol client. Its adapter sends Jaeger turns over the bridge socket, while the Gateway's HTTP session route can dispatch lead turns through the MCP/Agentgateway path (`:8811`) and specialist or explicit text-only turns directly to Ollama. Hermes native and OpenClaw native backends are real optional integrations, not the local Jaeger loop. Their availability or successful health probe does not prove a complete end-to-end turn.

No P0 defect was proven. A P1 operational risk is present: `jaeger doctor` cannot resolve the configured model (`gemma-4-e4b-it-q4_k_m`), so a fresh local Jaeger turn is not proven bootable from the current instance. A second P1 risk is architectural ambiguity: multiple legitimate turn paths exist and the normal production selection between bridge, Gateway/MCP, and direct model paths is not represented by one single runtime entry point.

## Repository and install truth

* `command -v jaeger` → `/Users/matthewjenkins/bin/jaeger`, a symlink to this checkout's `jaeger` launcher.
* The launcher executes `~/.jaeger/venv/bin/python -m jaeger_ai.cli.entry`; `pyproject.toml` also declares `jaeger_ai.cli.entry:main`.
* The venv reports `jaeger-ai 0.11.0`, editable location `/Users/matthewjenkins/GitHub/JaegerAI`; `jaeger-agent 1.0.0` and `jaeger-os 0.9.0` are also editable from `packages/` in this checkout.
* `jaeger --version` succeeds. `jaeger runtime` finds llama.cpp and MLX; `mlx-vlm` is absent.
* `scripts/install.sh` installs the in-repository `packages/jaeger-os`, `packages/jaeger-agent`, and voice packages before resolving the root requirements. Hermes is not a root Python dependency; the WebUI is vendored under `vendor/hermes-webui` and may optionally prepend `~/GitHub/hermes-agent` to `PYTHONPATH`.
* Current git state is intentionally dirty (`main...origin/main [gone]`, with many modified and untracked files). No cleanup or reset was performed. The SHA above is the code version audited; uncommitted changes may affect runtime behavior.

## Actual startup and dispatch

```text
bin/jaeger (symlink)
  -> repo/jaeger (sets bytecode/cache env)
  -> ~/.jaeger/venv/bin/python -m jaeger_ai.cli.entry
     ├─ ordinary prompt / --instance / --voice -> jaeger_ai.cli.run -> jaeger_ai.main
     ├─ bridge -> jaeger_ai.interfaces.bridge (NDJSON stdio + AF_UNIX attach socket)
     ├─ gateway daemon -> jaeger_ai.core.gateway.server (:8810)
     ├─ bare gateway -> jaeger_ai.features.agentgateway (:8811 MCP, :8812 A2A)
     ├─ mcp -> jaeger_ai.interfaces.mcp_server
     ├─ a2a -> jaeger_ai.interfaces.a2a_server
     └─ hermes-webui-adapter -> jaeger_ai.features.webui.adapter
```

The WebUI launcher runs `vendor/hermes-webui/server.py` on `8790`, sets Hermes state under the operator state root, points it at Gateway `8810`, and loads Jaeger extension assets. The adapter's `BridgeClient.turn()` speaks the Jaeger bridge protocol (`send`, streamed `delta/reasoning/tool/request`, then `reply`). The bridge eventually calls `jaeger_ai.main._run_turn` and returns the same result shape used by CLI/TUI/voice clients.

The Gateway HTTP path is separate:

```text
POST /v1/sessions/{id}/turns (:8810)
  -> admit request / persist turn
  -> JaegerGatewayApp._execute_turn
     ├─ lead, normal mode -> MCP client to configured MCP gateway (:8811)
     │                       -> jaeger_chat/chat tool -> native Jaeger runtime
     ├─ specialist or text_only -> locked Ollama /api/chat (:11434)
     └─ persist terminal result + publish SSE turn events
```

The Gateway deliberately marks an accepted native request as `execution_unknown` when the native result is not confirmed; it does not blindly retry an uncertain native call.

## Canonical turn, model, and tool path

For the ordinary local client, `jaeger_ai.main._run_turn_via_jaeger_agent` constructs or reuses a session agent, prepares the turn, and calls `jaeger_agent.loop.runtime_bridge.drive_one_turn`. That function calls the `JaegerAgent` loop (or its executive wrapper when state is bound), which obtains a provider response, interprets tool calls, and continues until a final answer or loop guard.

`jaeger_ai.main.make_client()` selects exactly one enabled external provider when configured (including Ollama/OpenAI-compatible providers), otherwise resolves a local GGUF/MLX engine. The live Gateway specialist fallback uses Ollama's native `/api/chat`; this is distinct from the local in-process llama.cpp/MLX selection used by the ordinary Jaeger process.

Tool execution is a real seam, not a comment-only abstraction: the JaegerOS `ToolDef` registry is registered by `jaeger_ai.main`, and the agent executor composes allowlisting, shell hooks, checkpoints, and an effect ledger. External side effects are keyed by run/tool/arguments and claimed through `EffectLedger.once`; mutating tools request a checkpoint before dispatch. The tests prove these boundaries, but no paid-provider or real external side-effect end-to-end run was performed in this audit.

## Agent and orchestration inventory

| Layer | Actual owner | Reachability/evidence | Finding |
|---|---|---|---|
| Product façade | `jaeger_ai.main` | CLI, bridge, TUI, voice, background callers | Primary host and result adapter |
| Inner agent loop | `packages/jaeger-agent/.../JaegerAgent` + `drive_one_turn` | Called directly by `main.py`, benchmarks, subagents | Canonical conversational/tool loop |
| Outer job controller | `JaegerAgentController` | Used by `autonomous_runner` and subagent worker paths | Batch/job state machine; not proven on ordinary chat path |
| Native Runs backends | `core/frameworks/backends.py` | Jaeger, Hermes, OpenClaw registrations | Structured run protocol for adapters; overlaps in concept with delegate registry |
| Delegate registry | `jaeger_agent.delegates` | `jaeger delegate list`, built-in registration | External CLI/process agents and optional Ollama delegate |
| WebUI surface | vendored Hermes WebUI + Jaeger adapter | Live `8790`; adapter code calls bridge | Client/proxy surface, but can load an external Hermes checkout |

This is a stack, not evidence of five independent Jaeger brains. The unresolved issue is ownership clarity: production behavior depends on which client and route was selected, and the repository does not expose one universal turn authority for all surfaces.

## Hermes, OpenClaw, and Ollama truth

* **Hermes:** The vendored WebUI is active. Hermes native runs use a container-discovered service and `~/.hermes/jaeger-native-api.key` through `core/frameworks/hermes_native.py`; this is an external service contract. `jaeger delegate list` currently reports Hermes unavailable because the detector encountered the system `/usr/bin/git` Xcode-license failure. This is not proof that the container/API is absent, only that the current probe cannot certify it.
* **OpenClaw:** A live listener exists on `127.0.0.1:18789`. The OpenClaw adapter supports legacy OpenAI-compatible chat and an opt-in native Runs mode (`OPENCLAW_ADAPTER_NATIVE_RUNS`). The token is state-rooted. It is optional and externally owned; its tool/effect execution is not Jaeger's local executor.
* **Ollama:** A live listener exists on `11434`. Ollama is both a model provider in the external-model router and a separate delegate option. Gateway specialist/text-only fallback calls `/api/chat` directly. `jaeger delegate list` reports the Ollama delegate unavailable unless `JAEGER_OLLAMA_DELEGATE_MODEL` is set; that is a configuration gate, not a server-health result.

## Live observations

At audit time, `lsof` showed listeners on `*:11434` (Ollama), `127.0.0.1:18789` (OpenClaw/container), `*:8790` (Hermes WebUI), and `*:8810` (Jaeger Gateway). Process listing was restricted by macOS permissions, so ownership was established by listening sockets and successful CLI probes rather than `ps`.

`jaeger doctor` exited nonzero. It reported an unresolved model path, no bound workspace for several checks, and `memory: OperationalError: attempt to write a readonly database`; it also reported healthy installed packages and writable logs. The doctor command is not a normal bound turn, so the workspace/database findings require confirmation in a real instance, but the unresolved model is an immediate startup concern.

## Tests and commands run

* `jaeger --version` — passed (`jaeger-ai 0.11.0`).
* `jaeger runtime` — passed; llama.cpp and MLX available, mlx-vlm absent.
* `jaeger delegate list --json` — passed; nine built-ins enumerated, with current availability details above.
* `jaeger doctor` — ran; exit 1 with the findings above.
* Root smoke via `dev/scripts/run_tests.sh --smoke` — 169 passed; JaegerOS portion — 283 passed.
* `packages/jaeger-agent/tests` with Homebrew Git in PATH — 908 passed.
* Gateway/adapter targeted tests — 50 passed.
* WebUI server-control tests — 8 passed.
* Swift package/product build with host Xcode permissions — **passed** (`Build complete!`, 14.38 sec); two non-fatal `await`/`async` warnings were emitted in `BridgeProcess.swift`.

These suites establish substantial unit/contract coverage. They do not establish a complete live user turn through every provider, Hermes native API, OpenClaw native Runs API, MCP gateway, and real side-effect tool.

## Ownership matrix

| Concern | Authoritative implementation | External/optional dependency | Status |
|---|---|---|---|
| CLI startup/routing | `jaeger_ai.cli.entry` | venv/editable install | Proven |
| Turn orchestration | `jaeger_ai.main` + `jaeger-agent` loop | Provider adapter | Proven by tests; live model turn not proven |
| Gateway sessions/SSE | `core.gateway.server` | SQLite under operator state | Live listener; targeted tests pass |
| Bridge protocol | `interfaces.bridge` | AF_UNIX socket under instance state | Covered; live socket not probed |
| Tool catalog/dispatch | JaegerOS registry + `jaeger-agent.tool_executor` | Shell hooks/checkpoint/ledger state | Covered by agent suite |
| Lead native route | Gateway → MCP client → `:8811` | Agentgateway/MCP credential | Not end-to-end proven |
| Specialist/text-only route | Gateway → Ollama `:11434/api/chat` | Ollama model | Listener present; model/result not proven |
| Hermes UI | `vendor/hermes-webui` + adapter | Optional external Hermes checkout | Live UI listener |
| OpenClaw | adapter/native backend | OpenClaw gateway/token | Listener present; optional route |

## Findings by severity

### P0 — none proven

No evidence of data loss, an always-on security bypass, or a universally broken production path was established.

### P1 — needs resolution before calling the runtime consolidated

1. **Configured local model is unresolved.** `jaeger doctor` cannot find `gemma-4-e4b-it-q4_k_m`; a fresh ordinary Jaeger turn is therefore not proven to boot from the current operator configuration.
2. **Multiple active turn authorities are selectable by route.** Bridge/`main`/`JaegerAgent`, Gateway/MCP native lead, Gateway/Ollama fallback, and optional native delegate backends all exist. Their contracts are intentional, but the default production route and single ownership boundary are not demonstrated by one end-to-end trace.

### P2 — material integration risks

1. Hermes and OpenClaw execute outside Jaeger's local tool/effect ledger when selected as external/native backends; Jaeger can relay events and reconcile status, but cannot claim their side effects in its own ledger.
2. The WebUI is a Hermes fork and can prepend an external `~/GitHub/hermes-agent` checkout, creating a second implementation source outside this repository.
3. Delegate availability is capability probing only. `available: true` for a CLI does not prove credentials, model access, tool execution, or result persistence.
4. `JaegerAgentController` is a real outer state machine used by autonomous/subagent paths, but its use by ordinary user chat is not proven; this is a likely source of “answer versus job completion” confusion.

### P3 — maintenance and release clarity

1. The audited install/version remains `0.11.0` while repository consolidation discussions reference `0.12.0` candidates.
2. The checkout is `main` with its remote deleted and a dirty tree; `master` remains the intended authoritative branch, but this runtime audit is of the actual installed checkout, not a clean master checkout.
3. The Swift application builds successfully; the compiler reports two non-fatal unnecessary-`await` warnings in `BridgeProcess.swift`.

### P4 — low-risk observations

1. `mlx-vlm` is an optional discovered engine and is not installed.
2. Some doctor checks intentionally require a bound workspace/instance and therefore fail when run as a standalone diagnostic.

## Unresolved questions

* Which client is the supported default for a new operator turn: bridge → `main`, Gateway → MCP native lead, or another launch wrapper?
* Is the configured model path stale, or is the model intentionally supplied by Ollama/OpenClaw for this installation?
* Is the live `8790` process using only the vendored WebUI or the optional external Hermes checkout?
* Are native Hermes/OpenClaw Runs expected to be authoritative product paths or compatibility adapters?
* Should autonomous `JaegerAgentController` semantics ever govern interactive chat, or remain job-only?
* Can a clean, bound instance pass `jaeger doctor` memory and workspace checks without changing code?

## Plain-English conclusion

Jaeger is not one monolithic executable, but it does have a recognizable core: `jaeger_ai.main` hosts the turn and `jaeger-agent` owns the inner reasoning/tool loop. The machine is currently running the surrounding services that the architecture describes. The repository is therefore substantially wired, with strong contract-test coverage, but it is not yet proven as one consolidated runtime because model startup is currently unresolved and several legitimate routes can own a turn. This report records those facts without changing them.
