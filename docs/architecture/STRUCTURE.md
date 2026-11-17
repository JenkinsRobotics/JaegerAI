# JaegerAI repo map

What lives where, as of 2026-11-17. If a folder is not listed here, it is not
part of the product. Code that was cut is on the Desktop under
`Jaeger-removed-features-2026-11-16/` (each folder has a README and a row in
`INDEX.md`), not in this repo.

## The running stack

| Service | Port | Code | Started by |
| :--- | :--- | :--- | :--- |
| Gateway | `127.0.0.1:33418` | `jaeger_ai/core/gateway/` | launchd `com.jenkinsrobotics.jaeger-gateway` |
| WebUI | `:8790` | `jaeger_ai/core/gateway/webapp/` + `jaeger_ai/interfaces/ui/` | the Gateway (same process) |
| MCP HTTP | `127.0.0.1:8792` | `jaeger_ai/interfaces/mcp_server.py` | launchd `com.jenkinsrobotics.jaeger-mcp-http` |
| Voice | `127.0.0.1:8794` | `jaeger_ai/core/voice/`, `packages/jaeger-kokoro-tts`, `packages/jaeger-whisper-stt` | `scripts/run-jaeger-voice.sh` (launchd) |
| Droid | — | `jaeger_ai/features/droid/` | launchd `com.jenkinsrobotics.jaeger-droid` |
| Mac app | — | `jaeger_ai/interfaces/macos-shell/` | the user; it loads the same frontend |

Port numbers have one home: `jaeger_ai/contract/ports.py`.
`scripts/verify-stack-smoke.py` checks all four ports; `scripts/verify-chat.py`
runs one real chat turn.

## Quick lookup

| I want to... | Look in |
| :--- | :--- |
| Change how a chat turn runs | `packages/jaeger-agent/jaeger_agent/` (loop, tools, memory), entered through `jaeger_ai/core/frameworks/jaeger.py` |
| Add or change a Gateway HTTP route | `jaeger_ai/core/gateway/server.py` and the `*_routes.py` beside it |
| Change a WebUI `/api/*` route or sign-in | `jaeger_ai/core/gateway/webapp/` (`jaeger_sessions.py`, `jaeger_signin.py`, `workspace_api.py`) |
| Edit the browser and Mac frontend | `jaeger_ai/interfaces/ui/src/` (React + TypeScript) |
| Edit the Mac host app | `jaeger_ai/interfaces/macos-shell/` (AppKit + WKWebView) |
| Add or change a skill | `packages/jaeger-agent/jaeger_agent/skills/` (`catalog.yaml` lists what ships) |
| Computer-control tools | the `computer_use_v1` and `macos_computer_v1` skills in that folder |
| Change MCP tools exposed to Codex / Claude Code | `jaeger_ai/interfaces/mcp_server.py`, `jaeger_ai/core/mcp/` |
| Change approvals and safety policy | `jaeger_ai/core/authority/`, `jaeger_ai/core/safety/` |
| Change memory | `jaeger_ai/core/memory/`, `packages/jaeger-agent/jaeger_agent/memory/` |
| Change the agent list (`/v1/agents`) | `jaeger_ai/core/agent_registry/` |
| Change Telegram / iMessage / Discord relays | `jaeger_ai/features/channels/` |
| Change a CLI command | `jaeger_ai/cli/verbs/` (router: `dispatch.py`) |
| Change shared names, ports, schemas | `jaeger_ai/contract/` (single copy; everything imports it) |
| Change the persona | `jaeger_ai/features/personality/` |

## Top level

```
.agents/        editor-agent rules
.github/        CI workflows, PR and issue templates
apps/           symlinks: macos -> jaeger_ai/interfaces/macos-shell, web -> jaeger_ai/interfaces/ui
clients/python/ thin Python client for the Gateway
dev/            tests, evals, benchmarks, dev scripts (never imported by the product)
docs/           product, stack, trust and architecture docs (index: docs/README.md)
jaeger          CLI launcher (./jaeger <verb>)
jaeger_ai/      the product
packages/       separately installable packages (agent, browser, OS, TTS, STT)
scripts/        install, verify and launch scripts
```

Root files: `README.md`, `AGENTS.md` (rules for coding agents), `CLAUDE.md`,
`CONTRIBUTING.md`, `SECURITY.md`, `DESIGN.md`, `CHANGELOG.md`,
`THIRD_PARTY_NOTICES.md`, `pyproject.toml`.

## jaeger_ai/

```
main.py           process entry
module_roots.py   where modules are discovered
cli/              the jaeger CLI; verbs/ holds one file per verb group
contract/         shared names, ports, schemas, trace and update contracts
core/             the runtime (below)
features/         optional capabilities, one folder each, each with a README
interfaces/       the ways in: UI, Mac app, MCP, A2A, IDE, TUI, bridge
plugins/          channel/plugin loader, Home Assistant, AI generation, MCP plugins
modules/          module shims for the bundled packages plus build-check
nodes/            animation and media nodes
assets/           icons, design system, connect-apps assets
migrations/       state migrations, run in order by the runner
docs/             in-package docs
```

### core/

```
gateway/          the Gateway server (server.py) and its route modules
gateway/webapp/   WebUI server side, folded into the Gateway (aliased as `api`)
frameworks/       turn entry (jaeger.py), native runs, delegation, discovery
agent_registry/   the agents shown in /v1/agents
authority/        tiered approval policy
safety/           safety checks around tools and actions
memory/           memory store and recall
models/           model routing and provider clients
runtime/          lifecycle, server controls, process supervision
skills/           skill service used by the Gateway
mcp/              MCP client/server plumbing
voice/            voice pipeline
team/, multi_agent/   team rooms and multi-agent runs
tasks/            task tracking
context_compiler/ prompt and context assembly
entity/, world/, devices/, capabilities/   embodiment and device model
instance/, settings/, secrets_env.py       instance layout, settings, secrets
diagnostics/, bench/                       diagnostics and benchmarks
```

### features/

`agent_bridge`, `app_control`, `browser`, `channels`, `cli_backends`,
`cost_tracking`, `dispatcher`, `droid`, `ide_orchestration`,
`knowledge_library`, `missions`, `notifications`, `obsidian`, `oss_stack`,
`personality`, `reasoning`, `remote_access`, `session_search`, `timeline`,
`ui_layout`, `voice`, `web_search`, `webhooks`, `workflows`.

Each folder's `README.md` says what it does, how to turn it on and how to
tell it works (enforced by `dev/tests/jaeger_ai/test_repo_structure.py`).

### interfaces/

```
ui/               shared React frontend (browser on :8790 and the Mac app)
macos-shell/      native Mac host
macos-pim/        Mac contacts/calendar helpers
mcp_server.py     MCP server (HTTP on :8792, or stdio)
a2a_server.py     agent-to-agent server (optional, not started by default)
bridge.py         in-process bridge used by clients and the Mac app
ide/              VS Code extension client
tui/              terminal UI
avatar/, native_multimodal/   avatar and multimodal surfaces
```

## packages/

| Package | What it is |
| :--- | :--- |
| `jaeger-agent` | the agent loop, tools, memory, skills (`jaeger_agent/skills/catalog.yaml`) |
| `jaeger-browser` | browser automation |
| `jaeger-os` | device and hardware layer |
| `jaeger-kokoro-tts` | local text-to-speech |
| `jaeger-whisper-stt` | local speech-to-text |

## scripts/

`install.sh`, `install-packages.py`, `install-droid.py`,
`install-jaeger-channels.sh`, `install-team-skills.sh`, `setup-mac-robot.sh`
(install); `run-jaeger-voice.sh` (voice launcher); `verify.sh`,
`verify-chat.py`, `verify-stack-smoke.py`, `check-installed-release.py`,
`ci-local.sh` (checks); `audit-guard.py` (pre-push guard);
`build-standalone-macos.py`, `bundle-macos-native.py` (Mac builds);
`migrate-webui-config.py`; `connectors/`.

## dev/

```
dev/tests/        pytest suite (unit, contracts, integration, e2e, acceptance)
dev/tests/fixtures, dev/tests/helpers   shared test data and helpers
dev/scripts/      run_tests.sh and other dev tools
dev/evals/, dev/benchmark/              evaluations and benchmarks
```

UI tests live next to the code in `jaeger_ai/interfaces/ui/src/**/*.test.ts(x)`;
shared UI test data is in `jaeger_ai/interfaces/ui/src/test/fixtures/`.

## Rules that explain the exceptions

1. One copy of everything. Ports, framework names and schemas live in
   `contract/`; a moved module gets its importers repointed, never a
   re-export shim (enforced by `test_repo_structure.py`).
2. Nothing is deleted outright. Cut code goes to the Desktop archive with a
   README saying how to restore it.
