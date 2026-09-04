<h1 align="center">JaegerAI</h1>

<p align="center">
  <em>Jaeger AI — powered by JaegerAgent on the JaegerOS framework, with local inference, tools, skills, memory, persona, chat/voice/TUI faces, and the client protocol.</em>
</p>

<p align="center">
  <a href="https://github.com/JenkinsRobotics/JaegerAI/releases"><img src="https://img.shields.io/badge/version-0.12.0-2EA44F?style=for-the-badge" alt="Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-2EA44F?style=for-the-badge" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+">
</p>

---

> **Jaeger ecosystem identity**
> ID: `org.jenkinsrobotics.app.jaeger-ai` · Type: **application** ·
> Role: reference intelligent application and module host

## What it is

JaegerAI is a complete **application** built on JaegerOS, alongside applications
such as JP01 and Mochi. It is not the operating-system framework and not the
reusable agent library. It ships a complete universal agentic experience
(Hermes lineage) by combining the reusable JaegerAgent brain with the
id/ego persona pipeline, local inference, **and its own faces** — chat
app, TUI, voice, and the protocol it serves. Headless (running on a
robot with no display) is a **config** of JaegerAI, not a fork of it.

**0.10 split complete:** the separately packaged
[JaegerAgent](https://github.com/JenkinsRobotics/jaeger-agent) mind module is
the reusable brain other projects embed. It owns the engine-neutral agent
loop, provider adapters, message schemas, context management, bus bridge, and
`slot: mind` node. JaegerAI imports that package and supplies its product tool
selection, instance layout, persona, interfaces, installer, and defaults
through explicit host hooks. JaegerAgent remains the owner of agent memory,
tools, skills, and the multimodal turn loop.

It pins [JaegerOS](https://github.com/JenkinsRobotics/JaegerOS) (the
framework tier — bus, nodes, modules/slots, supervisor, safety, wire
contract, capability layer) and builds everything agentic on top:

- **`modules/`** — provider-named application integrations for JaegerAgent,
  JaegerKokoroTTS, and JaegerWhisperSTT. These state how this app uses an
  imported module; engine implementation stays in its provider package.
- **`core/`** — Jaeger AI's application lifecycle, instance integration,
  policy, diagnostics, and the **`persona_first`** pipeline: an id/ego split
  where a persona lane speaks to the user directly, in character, and
  has exactly one tool — `perform_task(request)` — which runs the full
  clean inner agentic loop (persona-off, all tools, hardened prompt).
  The safety property in one line: *the id never touches reality
  directly.*
- **`characters/`** — 15 portable `character/v1` packs own identity + soul +
  traits + lore + assets as **State** (HEXACO/SPECIAL/Expression sliders),
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
  PySide6 Multimodal face. The Multimodal window is a renderer and device
  pump over `jaeger_agent`; the agent package owns its audio
  pipeline, turn policy, vision transport, and speech. All faces are clients
  of one protocol.
- **The client protocol** — JaegerOS's versioned contract plus
  `jaeger_ai/interfaces/client.py` (`JrosClient`), a
  versioned NDJSON wire contract any surface — including third-party
  ones — speaks over `jaeger bridge`.
- **`cli/`** — the `jaeger` command (every real verb: `status`, `config`,
  `runtime`, `agent create/list/use/inspect/delete`, `update`, …).
  JaegerOS ships no CLI at all — this repo is where it lives.

Engine modules ([JaegerKokoroTTS](https://github.com/JenkinsRobotics/JaegerKokoroTTS),
[JaegerWhisperSTT](https://github.com/JenkinsRobotics/JaegerWhisperSTT))
are **optional extras** — each its own repo, pinning JaegerOS only, so a
robot body can run without the AI product installed at all.

## Install

The standard product install is one command. It installs into `~/JaegerAI`,
builds the native **Jaeger AI** application, and adds it to Applications and
Launchpad on macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/JenkinsRobotics/JaegerAI/master/scripts/install.sh | bash
```

If it finds a 0.9-era `~/jaeger` install, it safely migrates `.jaeger_os/`
(agents, memory, settings, credentials, and active-agent selection) while the
old app is stopped. The old directory is retained as a rollback copy until you
verify the new app. Future upgrades use `jaeger update` or **Update now** in
Jaeger AI Settings.

For a development checkout:

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
JaegerOS: the code stays writable in place because the agent
self-modifies its own skills.

`pip install jaeger-ai` from PyPI is **(planned, 1.0)** — not available
yet.

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
./jaeger multimodal --check        # preflight models, mic, camera, engine
./jaeger multimodal --audio full --check  # also require the duplex AEC runtime
./jaeger multimodal                # launch the dedicated multimodal face
# Or double-click "Jaeger AI.app" at the repository root.
# Install a Spotlight/Launchpad launcher with one command:
./jaeger launcher install
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

### Runtime state ownership

JaegerAI owns deployed application instances under
`.jaeger_os/instances/<name>/`. Each instance has one identity, configuration,
memory database, logs, skills workspace, and process lock. At application boot,
JaegerAI injects that instance layout into JaegerAgent, so the reusable agent
reads and writes the same state; it does not create a second agent instance.

A `.jaeger_agent/` directory is JaegerAgent's standalone fallback when its CLI
or library is run directly without a host. It is not part of a hosted JaegerAI
instance and can coexist in a development checkout without being selected by
the application.

## Architecture

JaegerAI is an **application**. JaegerOS supplies the application/runtime
framework; JaegerAgent supplies the reusable agentic mind:

```
JaegerOS      ← application/runtime framework

JaegerAgent   ← reusable multimodal agentic mind

JaegerAI      ← YOU ARE HERE: an app using both layers, adding persona,
                product policy, interfaces, plugins, defaults, and the CLI

Modules       ← engine modules this repo can optionally install:
                JaegerKokoroTTS (tts), JaegerWhisperSTT (stt).

Other apps    ← JP01, Mochi, and future products can compose the same layers
```

The connection rule (from
[`JAEGER_ECOSYSTEM.md`](https://github.com/JenkinsRobotics/JaegerOS/blob/main/dev/docs/vision/JAEGER_ECOSYSTEM.md)):
**bodies provide capabilities · the Mind consumes them · the runtime is
where they meet · the protocol is how outside apps reach in.** See
[`THREE_TIER_STRUCTURE.md`](https://github.com/JenkinsRobotics/JaegerOS/blob/main/dev/docs/vision/THREE_TIER_STRUCTURE.md)
for the full tier-map reasoning this repo is built against.

## Ecosystem

| Repo | Tier | What |
|---|---|---|
| [JaegerOS](https://github.com/JenkinsRobotics/JaegerOS) | Framework | Bus, node, modules/slots, supervisor, safety, contract, capability layer. This repo pins it. |
| [JaegerAgent](https://github.com/JenkinsRobotics/jaeger-agent) | Agent module | Reusable multimodal agentic mind: loop, tools, skills, memory contracts, and capability nodes. |
| **JaegerAI** | Application | This repo — the reference agent application and its faces. |
| [JaegerKokoroTTS](https://github.com/JenkinsRobotics/JaegerKokoroTTS) | Engine module (`tts` slot) | Streaming Kokoro speech synthesis. Optional extra of this repo. |
| [JaegerWhisperSTT](https://github.com/JenkinsRobotics/JaegerWhisperSTT) | Engine module (`stt` slot) | Two-pass Whisper transcription with VAD + wake word. Optional extra of this repo. |
| JP01 | Project (Body) | The reference hardware Jaeger — installs this repo headless. |

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
