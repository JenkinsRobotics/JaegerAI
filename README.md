<h1 align="center">JaegerAI</h1>

<p align="center">
  <em>A general-purpose AI assistant platform — local or hosted models, tools, skills, memory, automation, delegation, and native chat, web, terminal, and voice experiences.</em>
</p>

<p align="center">
  <a href="https://github.com/JenkinsRobotics/JaegerAI/releases"><img src="https://img.shields.io/badge/version-0.11.0-2EA44F?style=for-the-badge" alt="Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-2EA44F?style=for-the-badge" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+">
</p>

---

> **Jaeger ecosystem identity**
> ID: `org.jenkinsrobotics.app.jaeger-ai` · Type: **application** ·
> Role: reference intelligent application and module host

## What it is

See the [documentation index](docs/README.md) for operator commands,
architecture, developer tooling, and integration notes.

JaegerAI is a complete, general-purpose assistant platform. It can answer
questions, work with files and code, browse and research, manage personal
information, run scheduled and background work, use external services, and
delegate larger jobs to other agent runtimes. It supports local, hosted, and
CLI-backed models and provides native desktop, web, terminal, voice, and
headless experiences.

JaegerAI combines the reusable JaegerAgent runtime with a broad tool surface,
skills, persistent memory, permissions, automation, model routing, and an
optional personality system. Voice, avatars, and physical-device capabilities
are extensions of the same assistant—not requirements and not its defining
scope. A laptop assistant, a private server, and a hardware deployment all run
the same product with different capabilities enabled.

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

- **`agent/`** — JaegerAI's product integration for JaegerAgent: toolsets,
  availability gates, prompts, skills, safety policy, and the
  **`persona_first`** pipeline (default since 0.8.0): an id/ego split
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
  frozen PySide6 shipping set. All faces are clients of one protocol.
- **The client protocol** — `jaeger_ai/contract` (vendored from
  JaegerAI) + `jaeger_ai/interfaces/client.py` (`JaegerClient`), a
  versioned NDJSON wire contract any surface — including third-party
  ones — speaks over `jaeger bridge`.
- **`cli/`** — the `jaeger` command (every real verb: `status`, `config`,
  `runtime`, `agent create/list/use/inspect/delete`, `update`, …).
  JaegerAgent ships no product CLI — this application repo is where it lives.

Engine modules ([JaegerKokoroTTS](https://github.com/JenkinsRobotics/JaegerKokoroTTS),
[JaegerWhisperSTT](https://github.com/JenkinsRobotics/JaegerWhisperSTT))
are independently usable components. They allow deployments to add speech
without coupling the underlying runtime to the complete assistant product.

## Install

The standard method is the same as pre-split JaegerAI: clone, run
`./install.sh`, keep current with `jaeger update`.

```bash
git clone https://github.com/JenkinsRobotics/JaegerAI.git
cd JaegerAI
./install.sh                       # venv + editable install of jaeger-os + jaeger-ai
./jaeger update                    # later: git pull + reinstall deps, non-interactive
```

`pip` is the machinery underneath: it resolves the dependency chain
across the five ecosystem packages (`jaeger-os`, `jaeger-agent`,
`jaeger-ai`, `jaeger-kokoro-tts`, `jaeger-whisper-stt`) — using sibling
editable checkouts for development and the git refs in `requirements.txt`
otherwise. JaegerAI installs **editable** (PEP 660), same model as
JaegerAI: the code stays writable in place because the agent
self-modifies its own skills.

The supported install is the repository installer above (or the one-line
installer in [`scripts/install.sh`](scripts/install.sh)). It creates an
isolated environment, installs the in-repository packages, builds the native
app when Swift is available, and preserves instance state across upgrades.
Direct `pip install jaeger-ai` from PyPI is not currently the release path.

Voice is optional — pull in the engine extras when you want speech:

```bash
pip install -e '.[kokoro_tts]'     # speak (JaegerKokoroTTS)
pip install -e '.[whisper_stt]'    # listen (JaegerWhisperSTT)
```

## Quick start

```bash
./jaeger agent create              # opens the setup wizard (character, model, permissions)
                                    # --tui for the terminal wizard
./jaeger                           # launch the default agent
```

Manage multiple agents — a character is the persona; an agent is a
deployed AI that plays one, with its own memory + config:

```bash
./jaeger agent list                # list agents / mark the default
./jaeger agent --help              # create | list | use | inspect | delete | clear
./jaeger --agent <name>            # launch a named agent
./jaeger --agent <name> --no-voice # text-only (no mic, no TTS warm)
```

`jaeger` is the one operator command — installed on `PATH` after
`install.sh`, or run as `./jaeger` from the clone.

### Jaeger WebUI

Jaeger's browser interface is its attributed, Jaeger-branded Hermes WebUI fork
at `vendor/hermes-webui`. Hermes supplies the frontend lineage; Jaeger owns the
runtime, sessions, tools, approvals, memory, models, heartbeat, and scheduled
work. Clone with `--recurse-submodules` (or run `git submodule update --init`),
then start the loopback adapter and browser server with one command:

```bash
./jaeger webui start --instance <agent-name>
```

The launcher configures the pinned WebUI to use the loopback adapter. Jaeger
WebUI serves the browser on port `8790`, while Jaeger remains the runtime owner for
sessions, streamed chat and reasoning, model selection, tools, approvals,
heartbeat, and scheduled jobs through its versioned bridge. The public WebUI
launch path runs `vendor/hermes-webui/server.py` directly: it does not discover,
run, or import Hermes Agent and stores no state under `~/.hermes`.
Third-party attribution is recorded in
`jaeger_ai/interfaces/hermes_webui_adapter/THIRD_PARTY_NOTICES.md`.

#### Alternative containerized WebUI

The Apple-container version remains available as an alternative development
surface. It is not required for the primary Jaeger WebUI path:

```bash
./jaeger settings set containers.use_hermes_webui true
./jaeger webui start --container
open http://127.0.0.1:8787/
```

Port map (defaults chosen to avoid clashes):

| Surface | Default | Notes |
| --- | ---: | --- |
| Hermes WebUI container (browser) | **8787** | Apple container `hermes-webui-hermes-webui` |
| Jaeger-branded vendor WebUI | **8790** | `./scripts/run-jaeger-webui.sh` |
| Hermes WebUI adapter | **8791** | `jaeger hermes-webui-adapter` / runner-local |
| Instance webhooks | **8793** | Moved off 8791 so adapter and webhooks do not collide |
| Jaeger MCP HTTP | **8792** | `jaeger mcp --http` (Agentgateway target) |
| Jaeger A2A backend | **8796** | `jaeger a2a` (Agentgateway proxies :8812 here) |
| Agentgateway MCP | **8811** | Jaeger-owned `jaeger gateway`; Hermes is a client |
| Agentgateway A2A | **8812** | Jaeger-owned public A2A card/JSON-RPC

`jaeger webui status` shows toggle state, container/adapter health, and URLs.

Jaeger owns Agentgateway. Install the public v1.5.0 binary with `jaeger gateway install`
(into `~/.jaeger/bin`), write `~/.jaeger/gateway/config.yaml`, then start MCP HTTP,
A2A, and the proxy:

```bash
jaeger mcp --http          # 127.0.0.1:8792/mcp, attaches to the live bridge
jaeger a2a                 # 127.0.0.1:8796 official a2a-sdk JSON-RPC
jaeger gateway start       # 8811 MCP + 8812 A2A, targeting those Jaeger backends
```

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

For the standard native development layout, start the browser process with:

```bash
./scripts/run-jaeger-webui.sh
```

The optional `jaeger_ai/assets/jaeger_webui_branding.js` extension replaces
the browser favicon and Apple touch icon with Jaeger's existing Mac app icon.
Enable it through Hermes WebUI's supported extension variables:

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

## Development

```bash
pytest dev/tests -m smoke          # ~30s sanity check
pytest dev/tests                   # full suite (204 test files)
./dev/benchmark/bench.py           # routing corpus — the ≥79/81 gate for any agentic-pipeline change
./dev/benchmark/scenarios.py       # 51-case hermetic full-system scenario suite
./dev/benchmark/scenarios.py --lane security   # the 15 security gates only
```

The 0.9 split validated this repo standalone before the filter-repo cut:
2490/2500 tests passing (0 real fails; the remainder were environment-only,
not code) plus an instance-boot-identical check — a real model + real
tools booting the same way post-split as pre-split.

Test markers (`slow`, `integration`, `model`, `ui`, `subprocess`,
`smoke`, `regression`) let CI and local iteration pick the right subset
— see `pyproject.toml`. Follow the ecosystem's conventions: no doc
describes behavior the code doesn't implement yet (mark it `(planned)`
instead), and any commit that changes behavior keeps its docs truthful
in the same commit.

---

## License

[Apache-2.0](LICENSE) © Jenkins Robotics
