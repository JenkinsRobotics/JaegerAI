<h1 align="center">JaegerAI</h1>

<p align="center">
  <strong>A local-first AI assistant platform with persistent memory, tools, skills, and multi-interface support</strong><br>
  <em>Mac app · Web UI · Terminal · Voice — one AI companion across all your devices</em>
</p>

<p align="center">
  <a href="#quick-start"><img src="https://img.shields.io/badge/▶_Get_Started-37B679?style=for-the-badge" alt="Get Started"></a>
  <a href="docs/getting-started.md"><img src="https://img.shields.io/badge/📖_Guide-5865F2?style=for-the-badge" alt="Guide"></a>
  <a href="https://github.com/JenkinsRobotics/JaegerAI/releases"><img src="https://img.shields.io/badge/version-0.13.0-2EA44F?style=for-the-badge" alt="Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-2EA44F?style=for-the-badge" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11--3.12-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11-3.12">
</p>

<p align="center">
  <a href="https://github.com/JenkinsRobotics/JaegerAI/stargazers"><img src="https://img.shields.io/github/stars/JenkinsRobotics/JaegerAI?style=social" alt="GitHub stars"></a>
  <a href="https://github.com/JenkinsRobotics/JaegerAI/network/members"><img src="https://img.shields.io/github/forks/JenkinsRobotics/JaegerAI?style=social" alt="GitHub forks"></a>
  <a href="https://github.com/JenkinsRobotics/JaegerAI/issues"><img src="https://img.shields.io/github/issues/JenkinsRobotics/JaegerAI" alt="GitHub issues"></a>
</p>

---

> **JaegerAI** — A persistent AI companion for your computer
> Local-first · Privacy-focused · Open source (Apache 2.0)

## What it is

JaegerAI is a persistent AI companion that lives on your computer. It remembers your work, helps with projects, runs tasks in the background, and talks to you through a Mac app, web browser, terminal, or voice — with the same memory and personality everywhere.

Under the hood, it's a persistent artificial entity with one continuing identity — it thinks through different models, acts through software and physical devices, remembers its life, learns capabilities, and appears through whatever body or interface is available.

**Current product definition (2026-10-22, see docs/PRODUCT.md):** JaegerAI is
a standalone intelligence stack — a platform for proactive, world-model AI
companions and operators. It is one identity that listens, sees live,
speaks to you, remembers you and your work, helps day to day, runs your
projects, and eventually moves in a robotic body, with the same memory and
the same approval gate in every case. It integrates with robot operating
systems (JROS/JaegerOS), CAD and simulation tools (Aether Suite or alternatives),
your NAS or file storage, and YouTube (real engineering work, the fastest
revenue engine). It is not a workspace hub, not a CAD suite, and not
a machine project. The app/runtime runs locally on your hardware,
but LLM work today uses cloud models — on-device is the goal to build
toward, not a current local-model claim. See docs/TRUST.md and docs/STACK.md.

That shapes every design decision here. The model is a component the entity
thinks with, not the thing itself — swap Ollama for Claude and the same
entity continues, with its memory, its learned skills, and its history
intact. Sessions, interfaces, and devices belong to the entity; it never
belongs to them. Identity survives a restart, a model change, and a move
from the desktop app to a phone browser to a terminal.

In practice, today, that means an assistant that works across your computer
and your accounts, keeps durable memory you can inspect, runs scheduled and
background work on its own, learns and stores verified procedures as skills,
and checks whether its actions actually happened rather than trusting what a
model said. It runs on your own hardware, with local, hosted, or CLI-backed
models, reachable from a desktop app, a browser, a terminal, or voice.

Physical embodiment is a supported direction, not a requirement — the same
entity runs headless on a server or drives hardware through JaegerOS.

What is actually built versus experimental versus planned is tracked in
[docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md), with
each claim marked. Contributor workflow is in
[CONTRIBUTING.md](CONTRIBUTING.md). Extensions use public contracts
([docs/EXTENSION_GUIDE.md](docs/EXTENSION_GUIDE.md)); do not edit
`EntityRuntime` to add a skill.

### What it can do

- **Work across your computer** — inspect and edit files, run code and shell
  commands, use the clipboard, control supported applications, and analyze
  images and documents under explicit permission policy.
- **Research and communicate** — browse and extract web sources and work with
  email, calendars, and contacts. Optional messaging plugins remain available
  for deployments that need them, but are not required for remote access.
- **Remember and organize** — maintain attributed persistent memory, search
  prior sessions, manage tasks and Kanban work, and keep a knowledge library.
- **Run ongoing work** — schedule jobs, execute background tasks, monitor
  heartbeats, and delegate bounded work to installed agent runtimes.
- **Use the model you choose** — run llama.cpp or MLX locally, connect to
  hosted APIs and OpenAI-compatible servers, or use installed Claude, Codex,
  Gemini, Grok, or Hermes CLIs as the active model.
- **Use it locally or remotely** — use the native desktop app, Jaeger WebUI,
  TUI, or voice loop locally; publish only the WebUI through Tailscale for
  private remote access.

Capabilities are discovered at runtime. Jaeger does not assume that a channel,
device, model, or credential exists simply because the platform supports it.
Permissions and availability gates determine what each assistant instance may
actually use.

The separately installable
[JaegerAgent](https://github.com/JenkinsRobotics/jaeger-agent) mind module is
the reusable brain other projects embed. It owns the engine-neutral agent
loop, provider adapters, message schemas, context management, bus bridge, and
`slot: mind` node. JaegerAI imports that package and supplies its product tool
bundle, prompts, skills, memory, personality system, interfaces, installer,
and defaults through explicit host hooks. The release repository vendors the
coordinated source packages under `packages/` so one checkout is sufficient.

It includes JaegerOS (the runtime foundation: bus, nodes, modules, supervisor,
safety, wire contract, and capability layer) and builds the assistant platform
on top:

- **`modules/`** — optional provider-named application integrations.
  JaegerKokoroTTS and JaegerWhisperSTT remain available for explicit tools or
  app-specific features. The attached Multimodal face uses JaegerAgent's own
  speech nodes; the legacy TUI retains a separate capture/STT adapter while
  sharing agent-owned final speech.
- **`core/`** — Jaeger AI's application lifecycle, instance integration,
  policy, diagnostics, and the **`persona_first`** pipeline: an id/ego split
  where a persona lane speaks to the user directly, in character, and
  has exactly one tool — `perform_task(request)` — which runs the full
  clean inner agentic loop (persona-off, all tools, hardened prompt).
  The safety property in one line: *the conversational persona never executes
  tools directly.*
- **`personality/`** — characters (14 shipped) own identity + soul +
  traits + lore as **State** (HEXACO/SPECIAL/Expression sliders),
  compiled on change — never per turn — into a **View** the model
  actually sees. An instance just *plays* a character; the character
  isn't the instance.
- **Memory** — subject-attributed SQLite (`subject/key/value/category/
  source/tags/note`), current-view semantics, provenance-tracked.
- **Skills** — self-contained (`SKILL.md` + optional tools + recipe);
  the agent researches, writes, smoke-tests, benchmarks, and versions
  its own skills.
- **Its own faces** — the Swift app (default windowed UI), the TUI
  (`jaeger_ai/interfaces/tui/`, the 0.1.0-lineage terminal surface,
  preserved alongside newer surfaces per standing convention), voice
  (via the `kokoro_tts`/`whisper_stt` engine-module extras), and the
  canonical Mac host and shared UI. All faces are clients of one protocol.
- **The client protocol** — `jaeger_ai/contract` (vendored from
  JaegerAI) + `jaeger_ai/interfaces/client.py` (`JaegerClient`), a
  versioned NDJSON wire contract any surface — including third-party
  ones — speaks over `jaeger bridge`.
- **`cli/`** — the `jaeger` command (every real verb: `status`, `config`,
  `runtime`, `agent create/list/use/inspect/delete`, `update`, …).
  JaegerAgent ships no product CLI — this application repo is where it lives.

Optional engine modules ([JaegerKokoroTTS](https://github.com/JenkinsRobotics/JaegerKokoroTTS),
[JaegerWhisperSTT](https://github.com/JenkinsRobotics/JaegerWhisperSTT))
are independently usable components. They allow deployments to add speech
without coupling the underlying runtime to the complete assistant product.

## Quick start

**New to JaegerAI?** Here's the fastest path from zero to your first conversation:

```bash
# 1. Clone and install (macOS: double-click "Install Jaeger AI.command" instead)
git clone https://github.com/JenkinsRobotics/JaegerAI.git
cd JaegerAI
./install.sh

# 2. Create your first AI agent (interactive setup wizard)
./jaeger agent create

# 3. Start chatting
./jaeger                    # Mac app (if built) or terminal UI
# OR
./jaeger webui start        # Browser interface at http://localhost:8790
```

**What you'll need:**
- **macOS 12+** or **Linux** (Ubuntu 22.04+ recommended)
- **Python 3.11 or 3.12** ([download](https://www.python.org/downloads/) or `brew install python@3.12`)
- **Xcode Command Line Tools** (macOS only): `xcode-select --install`
- **~15 GB free disk** (for local models, Playwright browser, and Python packages)
- **8 GB+ RAM** (16 GB recommended for local models)

> **No local GPU?** No problem. JaegerAI works with cloud models (OpenAI, Anthropic, Ollama Cloud, etc.). You can also use local models via Ollama, llama.cpp, or MLX on Apple Silicon.

---

## Install

The standard method is the same as pre-split JaegerAI: clone, run
`./install.sh`, keep current with `jaeger update`.

**Choose your installation method:**

| Method | Best For | Command |
|--------|----------|---------|
| **Double-click installer** | macOS users who want the easiest path | Double-click `Install Jaeger AI.command` |
| **Clone + install** | Developers, Linux users, customization | `git clone ... && ./install.sh` |
| **One-line curl** | CI, servers, minimal interaction | `curl -fsSL https://raw.githubusercontent.com/JenkinsRobotics/JaegerAI/master/scripts/install.sh \| bash` |

```bash
git clone https://github.com/JenkinsRobotics/JaegerAI.git
cd JaegerAI
./install.sh                       # external venv + all five monorepo packages
./jaeger update                    # later: git pull + reinstall deps, non-interactive
```

The installer builds wheels from this checkout's `packages/` directory in
external temporary directories, then installs JaegerOS, JaegerAgent, the voice
engines, and JaegerAI in dependency order. The environment defaults to
`~/.jaeger/venv` (`JAEGER_VENV` overrides it). Run the installer after source
updates to refresh installed code. Writable skills and operator state live
under `~/.jaeger`, or the configured state directory.

For the one-line installer, `JAEGER_INSTALL_ROOT` selects the source checkout;
`JAEGER_STATE_DIR` (then `JAEGER_HOME`) selects operator state.

The current native host is `jaeger_ai/interfaces/macos-shell`, loading the shared
`jaeger_ai/interfaces/ui` frontend. Build with `bash
jaeger_ai/interfaces/macos-shell/Scripts/build-shell.sh`; output is
`~/.cache/jaeger/macos-shell/JaegerShell.app` (`JAEGER_MAC_BUILD` overrides it).
This is currently a development bundle; production installation is deferred.
No old SwiftUI app is selected as a fallback. Archived implementations and remaining runtime
the recoverable Desktop archive are documented in
[scoped cleanup](docs/integration/SCOPED_CLEANUP.md).

The supported install is the repository installer above (or the one-line
installer in [`scripts/install.sh`](scripts/install.sh)). It creates an
isolated environment, installs the in-repository packages, builds the native
app when Swift is available, and preserves instance state across upgrades.
Direct `pip install jaeger-ai` from PyPI is not currently the release path.

The application installs JaegerAgent's `multimodal-duplex` dependencies by
default. The standalone JaegerAgent library keeps neural audio optional.
There are no `kokoro_tts` or `whisper_stt` extras on the JaegerAI package.

## Your first AI agent

<details open>
<summary><strong>🎯 Create your AI companion in 3 commands</strong></summary>

```bash
# 1. Create your agent (interactive wizard)
./jaeger agent create

# 2. Start chatting
./jaeger                 # Mac app or terminal
./jaeger webui start     # Or browser at http://localhost:8790
```

The wizard guides you through: **character** → **model** → **permissions** → **interface**.

</details>

**Quick reference:**

```bash
./jaeger agent list          # List all agents
./jaeger agent use <name>    # Switch default agent
./jaeger --agent <name>      # Launch specific agent
./jaeger "one-shot prompt"   # Quick question, print answer, exit
./jaeger --voice             # Voice mode (mic + speech)
```

**System checks:**

```bash
./jaeger multimodal --check              # Verify mic, camera, models
./jaeger multimodal --audio full --check # Also verify voice duplex
./jaeger doctor                          # Full environment check
./jaeger status                          # See what's running
```

**Advanced:**

```bash
./jaeger multimodal                # Attach voice to running agent
./jaeger launcher install          # Add to Applications/Launchpad
./jaeger agent inspect             # View agent config (no model boot)
./jaeger agent delete <name>       # Remove an agent
```

### Jaeger WebUI

Jaeger's first-party browser interface lives at
`jaeger_ai/features/webui`. Its browser source descends from Hermes WebUI and
retains the upstream MIT license, while Jaeger owns the runtime, sessions,
tools, approvals, memory, models, heartbeat, and scheduled work. Start the
loopback adapter and browser server with one command:

```bash
./jaeger webui start --instance <agent-name>
```

The launcher configures the WebUI to use the loopback adapter. Jaeger
WebUI serves the browser on port `8790`, while Jaeger remains the runtime owner for
sessions, streamed chat and reasoning, model selection, tools, approvals,
heartbeat, and scheduled jobs through its versioned bridge. The public WebUI
launch path runs `jaeger_ai/features/webui/server.py` directly: it does not discover,
run, or import Hermes Agent and stores no state under `~/.hermes`.
Third-party attribution is recorded in
`jaeger_ai/features/webui/adapter/THIRD_PARTY_NOTICES.md`.

Port map (defaults chosen to avoid clashes):

| Surface | Default | Notes |
| --- | ---: | --- |
| Jaeger WebUI | **8790** | `./scripts/run-jaeger-webui.sh` |
| Jaeger WebUI adapter | **8791** | `jaeger hermes-webui-adapter` / runner-local |
| Instance webhooks | **8793** | Moved off 8791 so adapter and webhooks do not collide |
| Jaeger MCP HTTP | **8792** | Native framework endpoint: `http://127.0.0.1:8792/mcp` |
| Jaeger A2A | **8796** | Native AgentCard and JSON-RPC endpoint |
| Agentgateway MCP | **8811** | Optional compatibility proxy to native MCP |
| Agentgateway A2A | **8812** | Optional compatibility proxy to native A2A |

`jaeger webui status` shows toggle state, container/adapter health, and URLs.

Jaeger owns Agentgateway. Install the public v1.5.0 binary with `jaeger gateway install`
(into `~/.jaeger/bin`), write `~/.jaeger/gateway/config.yaml`, then start MCP HTTP,
A2A, and the proxy:

```bash
jaeger mcp --http          # 127.0.0.1:8792/mcp, attaches to the live bridge
jaeger a2a                 # 127.0.0.1:8796 official a2a-sdk JSON-RPC
jaeger gateway start       # 8811 MCP + 8812 A2A, targeting those Jaeger backends
jaeger gateway verify      # protocol handshake, tools, bridge health, capability inventory, card
```

Codex, Claude Code, and native Hermes Agent profiles connect directly to
`127.0.0.1:8792/mcp`. The OpenClaw Apple container crosses the host boundary
through Jaeger's Agentgateway at `192.168.64.1:8811/mcp`. The generated contract is recorded under
`~/.jaeger/agent-network.json`; the proxy ports remain available for clients
that specifically require Agentgateway. Both proxy ports require the private
bearer stored at `~/.jaeger/gateway/mcp.token`; only its SHA-256 hash appears in
Agentgateway configuration.

The ARES Agentgateway plist and `~/.ares/gateway` config are archive. Do not start them.

Remote access stays disabled by default. Start both services on loopback and
publish only Jaeger WebUI through Tailscale Serve with:

```bash
./jaeger webui start --instance <agent-name> --tailscale
```

Jaeger WebUI continues to call the runtime adapter on loopback, so the adapter
is not exposed to the tailnet. To expose the adapter API itself, set a strong
bearer token and explicitly opt in:

```bash
export JAEGER_REMOTE_ACCESS_TOKEN="$(openssl rand -hex 32)"
./jaeger hermes-webui-adapter --host 0.0.0.0 --port 8791 --allow-remote
```

Remote requests must originate from Tailscale's `100.64.0.0/10` or
`fd7a:115c:a1e0::/48` ranges and send `Authorization: Bearer
$JAEGER_REMOTE_ACCESS_TOKEN` or hold a signed login session. Override the
accepted ranges with `JAEGER_REMOTE_TRUSTED_NETWORKS`; forwarded-IP headers are
ignored so an untrusted client cannot spoof a tailnet address.

OIDC Authorization Code + PKCE is enabled only when all required allow-list
settings are present: `JAEGER_OIDC_ISSUER`, `JAEGER_OIDC_CLIENT_ID`,
`JAEGER_OIDC_ALLOW_CLAIM`, and `JAEGER_OIDC_ALLOW_VALUES`. Set
`JAEGER_PUBLIC_BASE_URL` to the external HTTPS URL. Passkeys are instance
scoped, use WebAuthn origin/RP validation, and are bootstrapped from an already
authenticated session. The authentication implementation lives in separate
`features/oidc`, `features/passkeys`, and `features/remote_access` folders.

### External agent delegates

Jaeger can delegate a task to `claude`, `codex`, `grok`, `gemini`, `hermes`,
`openclaw`, `ollama`, `opencode`, or `cursor`. Each adapter lives in its own
feature folder under `jaeger_agent/delegates/`. Ask Jaeger to call
`list_delegate_runtimes` for live health/capabilities, then use
`delegate_task(runtime="codex", goal="...")` or `runtime="auto"` for ranked
routing. Set `JAEGER_OLLAMA_DELEGATE_MODEL` to enable the local Ollama delegate.
Private and secret tasks are rejected unless the selected runtime is explicitly
local.

### CLI backends are models; delegates are workers

The same installed CLIs (`claude`, `codex`, `grok`, `gemini`, `hermes`)
are first-class **models** in Jaeger's own loop when they are on PATH.
`jaeger backends` probes them; they appear in the model catalog as
`cli:claude` (provider `claude-cli`, location `local-cli`). Select one
as the active brain with `/model use cli claude` — Jaeger keeps tools,
memory, and permissions. `delegate_task` is still the worker path: go
do this whole job in that agent. Do not confuse the two.

### ARES absorption and migration

Imported product capabilities are split by feature under `jaeger_ai/features/`;
delegate implementations are split by runtime under
`packages/jaeger-agent/jaeger_agent/delegates/`. The `ares_migration` feature
provides a read-only audit, idempotent state import, restricted backup, and a
retirement rehearsal. It imports ARES sessions, documents, schedules, worker
health observations, passkeys, and Kanban state without modifying ARES. ARES
must remain installed until the rehearsal reports no blockers.

### Running the WebUI in development

For the standard native development layout, start the browser process with:

```bash
./scripts/run-jaeger-webui.sh
```

The optional `jaeger_ai/assets/jaeger_webui_branding.js` extension replaces
the browser favicon and Apple touch icon with Jaeger's existing Mac app icon.
Enable it through Jaeger WebUI's supported extension variables:

```bash
export HERMES_WEBUI_EXTENSION_DIR="$PWD/jaeger_ai/assets"
export HERMES_WEBUI_EXTENSION_SCRIPT_URLS=/extensions/jaeger_webui_branding.js
```

## Architecture

JaegerAI separates the reusable runtime, agent engine, optional engines, and
complete product so each layer can evolve without forcing a particular user
interface or deployment shape:

```
JaegerOS      ← runtime, capability bus, nodes, supervision, and safety
JaegerAgent   ← reusable agent loop, tools, skills, and model adapters
JaegerAI      ← complete assistant product, policy, memory, and interfaces
Modules       ← optional engines this product can install:
                JaegerKokoroTTS (tts), JaegerWhisperSTT (stt).
Deployments   ← desktop, server, team, embedded, or hardware configurations
```

The connection rule (from
[`JAEGER_ECOSYSTEM.md`](https://github.com/JenkinsRobotics/JaegerAI/blob/main/packages/jaeger-os/dev/docs/vision/JAEGER_ECOSYSTEM.md)):
**hosts expose capabilities · the assistant uses them through policy · the
runtime coordinates execution · protocols connect external clients.** See
[`THREE_TIER_STRUCTURE.md`](https://github.com/JenkinsRobotics/JaegerAI/blob/main/packages/jaeger-os/dev/docs/vision/THREE_TIER_STRUCTURE.md)
for the full tier-map reasoning this repo is built against.

## Ecosystem

| Repo | Tier | What |
|---|---|---|
| JaegerOS (`packages/jaeger-os`) | Runtime | Bus, nodes, modules, supervisor, safety, contracts, and capabilities. |
| JaegerAgent (`packages/jaeger-agent`) | Agent engine | Model adapters, agent loop, tools, skills, context, and delegation. |
| **JaegerAI** | Assistant platform | This repository: the complete product, policy, memory, automation, and interfaces. |
| [JaegerKokoroTTS](https://github.com/JenkinsRobotics/JaegerKokoroTTS) | Engine module (`tts` slot) | Streaming Kokoro speech synthesis. Optional extra of this repo. |
| [JaegerWhisperSTT](https://github.com/JenkinsRobotics/JaegerWhisperSTT) | Engine module (`stt` slot) | Two-pass Whisper transcription with VAD + wake word. Optional extra of this repo. |
| JP01 | Example deployment | A hardware deployment that runs the same assistant headlessly. |

Two more repos round out the ecosystem without being part of the tier map
themselves: [JaegerTemplate](https://github.com/JenkinsRobotics/JaegerTemplate)
(the conventions every new ecosystem repo — this one included — started
from) and [JP01_Firmware](https://github.com/JenkinsRobotics/JP01_Firmware)
(the robot's Mac + Jetson body-side code JP01's headless install of this
repo ultimately talks to).

## Community & Support

JaegerAI is an open-source project. We'd love to have you join us!

| Resource | Link | What You'll Find |
|----------|------|------------------|
| 💬 **Discussions** | [GitHub Discussions](https://github.com/JenkinsRobotics/JaegerAI/discussions) | Ask questions, share setups, show off your agents |
| 🐛 **Bug Reports** | [GitHub Issues](https://github.com/JenkinsRobotics/JaegerAI/issues) | Report bugs, request features |
| 📖 **Documentation** | [docs/](docs/) | Guides, architecture, API reference |
| 💡 **Ideas & Roadmap** | [GitHub Projects](https://github.com/JenkinsRobotics/JaegerAI/projects) | What we're building next |
| 🤝 **Contributing** | [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute code, docs, or ideas |
| 📜 **Changelog** | [CHANGELOG.md](CHANGELOG.md) | What's new in each release |

### Getting Help

1. **Check the docs** — [Getting Started](docs/getting-started.md), [Commands](docs/COMMANDS.md), [Troubleshooting](docs/OPERATIONS.md)
2. **Run diagnostics** — `./jaeger doctor` checks your setup
3. **Search existing issues** — Your question might already be answered
4. **Ask in Discussions** — For usage questions and community help
5. **Open an issue** — For confirmed bugs or feature requests

### Contributing

We welcome contributions of all kinds:
- 🐛 **Bug fixes** — Fix issues, improve stability
- ✨ **Features** — New tools, interfaces, integrations
- 📝 **Documentation** — Guides, examples, clarifications
- 🎨 **Design** — UI/UX improvements, icons, branding
- 🧪 **Testing** — Test coverage, benchmarks, scenarios
- 💬 **Community** — Answer questions, review PRs

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

---

## Development

```bash
pytest dev/tests -m smoke          # ~30s sanity check
pytest dev/tests                   # full suite
./dev/benchmark/bench.py           # routing corpus — the ≥79/81 gate for any agentic-pipeline change
./dev/benchmark/scenarios.py       # 51-case hermetic full-system scenario suite
./dev/benchmark/scenarios.py --lane security   # the 15 security gates only
```

Test markers (`slow`, `integration`, `model`, `ui`, `subprocess`,
`smoke`, `regression`) let CI and local iteration pick the right subset
— see `pyproject.toml`. Follow the ecosystem's conventions: no doc
describes behavior the code doesn't implement yet (mark it `(planned)`
instead), and any commit that changes behavior keeps its docs truthful
in the same commit.

---

## License

[Apache-2.0](LICENSE) © Jenkins Robotics
