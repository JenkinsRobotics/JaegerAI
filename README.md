<!-- Banner — drop an image at assets/banner.png, then uncomment ↓
<p align="center">
  <img src="assets/banner.png" alt="JROS" width="100%">
</p>
-->

<h1 align="center">JROS — Jaeger Robot Operating Software</h1>

<p align="center">
  <em>A Mac-native, Python-first operating framework for embodied AI agents.</em>
</p>

<p align="center">
  <a href="https://github.com/JenkinsRobotics/JROS/releases"><img src="https://img.shields.io/badge/version-0.8.0-2EA44F?style=for-the-badge" alt="Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-2EA44F?style=for-the-badge" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux-555555?style=for-the-badge" alt="Platform">
  <a href="https://discord.gg/sAnE5pRVyT"><img src="https://img.shields.io/badge/Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://www.youtube.com/@Jenkins_Robotics"><img src="https://img.shields.io/badge/YouTube-FF0000?style=for-the-badge&logo=youtube&logoColor=white" alt="YouTube"></a>
</p>

---

## What is JROS?

JROS is the operating framework for **Jaegers** — humanoid robots, drones,
and digital AI agents that share a single coherent runtime. It provides the
**nervous system** (transport, nodes, topics) and the **brain** (agent loop,
memory, learned skills) so the same agent code runs on an LED-faced drone or
a chat-only desktop companion.

Built from real hardware pain, JROS runs on Apple Silicon and Jetson Orin —
no Docker, no special OS versions, no dependency hell. **One curl line
installs the whole stack.**

- 🧠 **Local-first** — runs entirely on-device on an in-process LLM. No cloud account required.
- 🛠️ **~100 built-in tools + 99 recipe skills** — files (read / write / edit / search), memory, web, code execution, scheduling, background processes, kanban, delegation, computer use. A CORE set is always visible; the rest are reachable via `describe_tool` / `load_toolset` when scoping is enabled.
- 📋 **Kanban task board** — the agent plans multi-step work as cards; Deep Think jobs live on the same board. `/board` to view it.
- 📚 **Self-authored skills** — the agent researches, writes, smoke-tests, benchmarks, and versions its own skills.
- 🖥️ **Computer use** — the flagship skill: drive any macOS app through the accessibility tree (see the screen, click, type, work menus).
- 🌙 **Deep Think** — an idle "deep sleep" mode that swaps to a heavier model and drains a skill-development queue via a staged plan→execute→verify runner.
- 🔌 **Model-agnostic** — opt into LM Studio, an OpenAI-compatible endpoint, or Anthropic Claude. Local stays the default.
- 🔒 **Permission-gated** — every tool is gated; risky actions are confirmation-prompted and audit-logged. Two modes: `confirm` (ask first) and `allow`.
- 🎭 **Agent ≠ character** — the agent's name and profile picture are the instance's own; a character is only the persona it plays, swappable without changing the agent's identity.
- ⏰ **Reminders & scheduled tasks** — "remind me in 5 minutes" fires once and completes itself (native one-shot, 0.7.2); cron expressions cover recurring automations. Scheduled prompts run as full agent turns — they can speak, message, or use any tool.
- 🔗 **Third-party API** — embed a JROS agent in your own app: a single-file, zero-dependency Python client ([`clients/python/jros_client.py`](clients/python/jros_client.py)) over the `jaeger bridge` NDJSON protocol, the same fixture-pinned contract the native Mac app speaks. See [Third-party apps](#third-party-apps--integrate-jros).
- 🤖 **Embodiment-ready** — the body contract and the capability-gated skill loader are already in place for hardware.

> **Status — `0.8.0` (the modular-runtime release).** The runtime is now ONE
> unified stack (one bus, one Node class, supervisor-owned workers), and
> capabilities are **engine-modules** in the ROS spirit — `kokoro_tts`,
> `whisper_stt`, `animation`, `media` are self-contained folders (node +
> engine + config + `module.yaml` + tests) bound by slot; swap an engine by
> flipping a module. The persona pipeline is **persona-first** ("the id and
> the ego"): your character answers conversation directly (~10x faster chat)
> and calls the clean task agent as its one tool — security-gated 15/15,
> delegation 12/12. Plus: agent name vs character preset finally separated
> end-to-end, New Chat + History in the app, in-app updates (daily check +
> one-click update), and the full-system scenario suite now tests the real
> user path. Hardware/capability-layer integration is 0.9's headline.
>
> **`0.7.2`.** The 0.7.x patch line polished the out-of-box flow:
> end-user installs build the product `JaegerOS.app` and first-run setup is
> the app's setup window (0.7.1); a third-party client API shipped
> (`clients/python/jros_client.py` + the documented bridge protocol, 0.7.1);
> reminders got a native one-shot (`in_minutes`/`at` — no more cron
> arithmetic for "in 5 minutes"), skill loads show in the chat as
> "skill · view scheduling" chips, and `./jaeger` now detaches from the
> terminal so the window can close (0.7.2).
>
> **`0.7.0` (Swift-first + the two-runner core).** JROS is now a
> **native Mac app**: `JaegerOS.app` is the primary UI (menu-bar resident,
> splash → chat/settings windows, quit-from-tray), talking to the Python core
> over a versioned NDJSON bridge (ready in ~0.5s; the model warms behind it).
> `JaegerOS-dev.app` is pinned to the dev instance. The agentic core runs a
> **two-runner** architecture: a soft-loop/hard-boundary realtime runner
> (verify gate + persona output filter) and a staged plan→execute→verify
> Deep Think pipeline, with **dual-context inference lanes** (persona-ON warm
> ttft **45.6s → 0.71s**). Benched at **E4B 79/81** (routing corpus) plus a
> new **51-case hermetic scenario suite** (security 14/15 on the 4B, 15/15 on
> the 26B). Operators manage **agents** (`jaeger agent …`) — each *plays* a
> character: the agent's **name and profile picture** are the instance's own
> (identity.yaml) and never change with the persona ("name your robot Ted, it
> plays HAL"). 99 self-improvable skills, subject-attributed SQL memory,
> HomeAssistant / fal.ai plugins.
>
> The recent arc: **0.4.0** introduced the node architecture (the `ZmqBus` +
> body contract); **0.5.0** folded the Mochi project in (character system,
> animation/media nodes); **0.6.x** delivered the install/update/lifecycle
> theme; **0.7.0** shipped the Swift-first app, the measured two-runner core,
> the identity-vs-character split across every surface, and the scenario
> benchmark. Jaeger Studio was extracted to its own repo.
>
> Full per-release write-ups live in
> [`dev/docs/revision_summaries/`](dev/docs/revision_summaries/); the running
> changelog is [`CHANGELOG.md`](CHANGELOG.md).

---

## The Two Layers

```
┌────────────────────────────────────────────────────────────┐
│                      AGENT (BRAIN)                          │
│         perceive → plan → act    +  memory  +  skills        │
│         one loop per Jaeger body                             │
└──────────────────────────┬─────────────────────────────────┘
                           │  invokes
┌──────────────────────────▼─────────────────────────────────┐
│                   NODES (NERVOUS SYSTEM)                     │
│    tts │ stt │ llm │ vision │ motors │ leds │ mcu_serial     │
│    pluggable, hot-swappable, transport-agnostic              │
└──────────────────────────────────────────────────────────────┘
```

**Nodes** are processes that do one thing — capture audio, run TTS, drive
servos, talk to a Teensy. They speak over standardized topics (ZMQ + UDP).

**Agents** are the brain. They subscribe to perception topics, reason with
an LLM, look up memories, plan an action sequence, and dispatch it to nodes.

A Jaeger is the union of **one agent loop** and **a configured set of nodes**.

---

## Prerequisites

- **Python 3.11 or 3.12** (not 3.13 yet — some native deps lack 3.13 wheels).
- **A C/C++ toolchain** — `llama-cpp-python` and `pywhispercpp` build
  native code. macOS: `xcode-select --install`. Debian/Ubuntu:
  `sudo apt install build-essential`.
- **PortAudio** — for microphone / speaker I/O. macOS: `brew install portaudio`.
  Debian/Ubuntu: `sudo apt install portaudio19-dev`.

## Quick Start

**One-line install** — clones JROS to `~/jaeger`, sets up a venv,
installs the full runtime, scaffolds `~/.jaeger/`:

```bash
curl -fsSL https://raw.githubusercontent.com/JenkinsRobotics/JROS/master/scripts/install.sh | bash
```

Then:

```bash
cd ~/jaeger
./jaeger agent create    # create your first agent — opens the setup app
                         # (character, model, permissions); --tui for the
                         # terminal wizard
./jaeger                 # launch the default agent
```

`jaeger` is the one operator command. Add `~/jaeger` to your `PATH` (the
installer prints the exact line) to drop the `./` and run `jaeger` from
anywhere; `./run.sh` still works as an alias.

Or scaffold a named agent:

```bash
./jaeger agent create --name ted  # "ted" is the agent's name — editable
                                   # later, never blank; the wizard defaults
                                   # to your character pick when omitted
./jaeger --agent ted              # launch "ted"
```

Manage multiple agents (a character is the persona; an agent is a deployed AI
that plays one, with its own memory + config):

```bash
./jaeger agent list           # list agents / mark the default
./jaeger agent --help         # create | list | use | inspect | delete | clear
```

That's the whole flow. The single install pulls the **entire**
runtime — local LLM, Kokoro TTS, Whisper STT, vision, the
external-model pipeline, messaging bridges. Nothing is left behind
an extra. A GGUF model is fetched from Hugging Face on first run, and
nothing else phones home.

**Upgrades** — one command, in place (no git needed on the unit):

```bash
jaeger update                 # download + apply the latest release; keeps your
                              # .venv + agent state untouched
jaeger update --rollback      # revert to the previous version
jaeger update --ref 0.6.0     # pin a specific version
```

`jaeger doctor` tells you when a newer release is available. (Re-running the
curl one-liner also works.)

**Pinning a release** — for reproducible installs:

```bash
JAEGER_REF=0.5.2 curl -fsSL \
  https://raw.githubusercontent.com/JenkinsRobotics/JROS/0.5.2/scripts/install.sh | bash
```

**Custom install location** — override with an env var:

```bash
JAEGER_HOME=/opt/jaeger curl -fsSL \
  https://raw.githubusercontent.com/JenkinsRobotics/JROS/master/scripts/install.sh | bash
```

**Where everything lives** — two clear buckets, side by side:

| Layer | Path | What |
|---|---|---|
| **Framework** | `~/jaeger/jaeger_os/` | The code (upgraded in place by `jaeger update`) |
| **Operator state** | `~/jaeger/.jaeger_os/instances/<name>/` | Each agent's persona, config, memory, skills, prompts, workspace, logs, credentials — one folder per agent |

The two sibling dirs at the install root make the framework / operator
split obvious. Operator state is fully `.gitignore`d; framework upgrades
never touch it. See [`dev/docs/reality/system_runtime_user.md`](dev/docs/reality/system_runtime_user.md)
for the design rationale.

**Manual install (no curl)** — if you'd rather see every step:

```bash
git clone https://github.com/JenkinsRobotics/JROS.git ~/jaeger
cd ~/jaeger
./install.sh
./jaeger agent create   # create your first agent
./jaeger                # launch it
```

---

## Third-party apps — integrate JROS

Any app can embed a JROS agent by driving the install's `jaeger bridge` — a
stdio NDJSON transport speaking the v1 client protocol (the same one the
native Swift app uses). Your app ships **no** JROS code and installs **no**
second copy: it drives the existing `~/jaeger` install and runtime.

**Python apps** — copy the single-file client
[`clients/python/jros_client.py`](clients/python/jros_client.py) into your
project (stdlib only, zero dependencies):

```python
from jros_client import JrosClient

with JrosClient() as jros:            # finds ~/jaeger (or $JAEGER_HOME)
    reply = jros.turn("hello", session="myapp")
    print(reply["text"])
```

Pick an agent with `JrosClient(instance="lilith")`; stream tool/state events
and answer the agent's permission prompts via the `turn()` callbacks.

**Any other language** — spawn `~/jaeger/jaeger bridge` and speak the NDJSON
frames documented in
[`jaeger_os/interfaces/protocol.py`](jaeger_os/interfaces/protocol.py)
(pinned by `protocol_v1_fixtures.json`, the same contract fixtures the Swift
client is tested against). The Swift app under `jaeger_os/interfaces/swift/`
is a complete worked example.

**MCP hosts** — `jaeger mcp` exposes the agent as an MCP server.

A localhost HTTP/WebSocket gateway (`jaeger serve`) is planned for 0.8, for
web UIs and clients that can't spawn a subprocess.

---

## Daily use

`jaeger` (or `./jaeger` from the install dir) is the operator surface — it
boots the agent app **detached**, so the terminal window can be closed (app
log: `.jaeger_os/logs/JaegerOS.log`; `JAEGER_ATTACH=1` to keep it attached).
`--tui` runs it in the terminal instead. `./jaeger autostart enable` makes it
launch at login. Pick whichever launch path matches what you're doing.

**Run a named agent** — the production flow:

```bash
./jaeger --agent lilith            # launch the 'lilith' agent
./jaeger --agent lilith --no-voice # text-only (no mic, no Kokoro warm)
```

**Dev loop** — for working on JROS itself (one line to set up):

```bash
curl -fsSL https://raw.githubusercontent.com/JenkinsRobotics/JROS/master/install.sh | bash
```

That clones the repo, builds the venv, and produces **`JaegerOS-dev.app`**
at the repo root — the windowed dev shell, pinned to the gitignored
`jros-dev` instance. Double-click it, or drive everything through the
`jaeger` CLI:

```bash
open JaegerOS-dev.app              # the windowed dev shell (menu-bar tray)
./jaeger dev                       # same, from the terminal
./jaeger dev --tui                 # the terminal (TUI) agent
./jaeger update                    # git pull + reinstall deps + rebuild app as needed
./jaeger dev --health              # preflight checks and exit
./jaeger dev --status / --stop     # singleton management
./jaeger dev --reset-audio         # sudo killall coreaudiod
```

The end-user app is `JaegerOS.app` (default instance) — built with
`jaeger_os/interfaces/swift/Scripts/build-app.sh --release --install`.

The `jaeger dev --health` preflight runs every check before handing off:
sandbox bundle, library import resolution, instance manifest schema,
GGUF model on disk, AVAudioEngine bridge import, Whisper assets,
Kokoro package, skill registry walk, TUI module import.  A red row
stops boot with the actual reason.

**Pick the audio backend** — JROS ships two persistent-stream backends
for TTS.  Configure once in your agent's `config.yaml`:

```yaml
voice:
  audio_backend: sounddevice    # PortAudio (default; macOS Settings-default device live-resolved)
  # or:
  # audio_backend: avaudio       # PyObjC AVAudioEngine, direct AVAudioPlayerNode scheduling
```

Or override per-run without editing the config:

```bash
JAEGER_AUDIO_BACKEND=avaudio ./jaeger
JAEGER_AUDIO_OUTPUT="Mac Studio Speakers" ./jaeger   # sounddevice device override
```

**Bench the agent** — two complementary suites:

```bash
./dev/benchmark/bench.py                       # routing corpus (E4B 79/81)
./dev/benchmark/scenarios.py                    # 51-case hermetic scenario suite
./dev/benchmark/scenarios.py --lane security    # the 15 security gates only
./dev/benchmark/scenarios.py --list             # list cases, no model boot
```

`bench.py` is the routing corpus (the ≥79/81 gate for any agentic-pipeline
change). `scenarios.py` is the full-system suite — multi-turn, run against a
throwaway temp instance so it can't touch live state; a security-gate failure
exits non-zero.

---

## Architecture direction (0.4+)

**The brain shipped first; 0.4.0 wired the spine** — the node-based
embodied architecture (the `ZmqBus` + body contract) that turns JROS from a
Mac-side agent into a robot operating framework that drives JP01-class
hardware. 0.5–0.6 built out the product around it; hardware adapters are next.

The position no one else owns:

> **JROS = ROS + Agentic AI + Mac-first local hardware.**
> One developer, one Mac, one robot.  Local LLM thinks; dedicated
> hardware nodes do the perception and action.  Same code laptop or
> fleet, no Docker, no cloud.

### The 0.4 picture

```
                   ┌──────────────────────────────────────┐
                   │           BRAIN NODE  (Mac)           │
                   │                                       │
                   │   LLM (Gemma) + agent loop            │
                   │   In-process: tools, memory, skills,  │
                   │                permissions, persona   │
                   │                                       │
                   │   Tools = networking shims:           │
                   │     text_to_speech → /act/speech      │
                   │     listen         → /sense/transcript│
                   │     vision_analyze → /sense/vision_analysis │
                   │     computer_use   → /act/motion etc. │
                   └────────────┬──────────────────────────┘
                                │ ZMQ pub/sub (or inproc in monolith mode)
              ┌─────────────────┼──────────────────┐
              │                 │                  │
     ┌────────▼─────┐   ┌───────▼──────┐   ┌───────▼──────┐
     │  audio_in    │   │   audio_out  │   │   vision     │
     │  (Mac mic)   │   │   (Mac spk)  │   │   (Jetson)   │
     └──────┬───────┘   └──────▲───────┘   └──────────────┘
            │                  │
     ┌──────▼───────┐    ┌─────┴────────┐
     │   stt        │    │   tts        │   ← own nodes, backend-swappable
     │  (Whisper)   │    │  (Kokoro)    │     (tomorrow: MLX-TTS, NeuTTS,
     └──────────────┘    └──────────────┘      Mistral Voxtral STT, …)
            │
            ▼ /sense/transcript      ┌─────────────────────────────────┐
                                     │  Canonical topic namespaces      │
                                     │    /sense/audio_in   binary mic  │
                                     │    /sense/transcript  STT text   │
                                     │    /sense/camera_frame raw frames│
                                     │    /sense/vision_analysis scene  │
                                     │    /sense/proprio     encoder+IMU│
                                     │    /act/speech        text→TTS   │
                                     │    /act/audio_out     binary spk │
                                     │    /act/motion        motor cmd  │
                                     │    /act/light         LED cmd    │
                                     └─────────────────────────────────┘
              ┌─────────────────────────────────┐
              │                                 │
     ┌────────▼─────────┐              ┌────────▼────────────┐
     │  motor_ctrl      │              │   led_ctrl          │
     │  (ESP32, MC01)   │              │   (Teensy, AVC01)   │
     └──────────────────┘              └─────────────────────┘
```

**Key architectural decisions** (locked 2026-06-06):

1. **One brain process, N hardware-bound peripheral nodes.**  Not
   one-node-per-tool — that's the ROS 2 mistake (extreme
   granularity).  The brain's tools, memory, and skill registry
   stay in-process for sub-microsecond function-call latency.
2. **STT and TTS get their own nodes.**  Voice pipelines evolve;
   today's Kokoro becomes tomorrow's MLX-TTS without touching the
   brain.  Same topic contract, swap the subscriber.
3. **Tool ↔ node contract** — *"A tool does the networking, the
   node does the execution."*  The agent's tool signatures
   (`text_to_speech("hi")`, `listen(seconds=5)`) stay identical.
   What changes is the implementation: in-process call becomes
   `bus.publish("/act/speech", …)` + correlation-ID wait for the
   `/sense/spoken` ack.
4. **The brain doesn't know where its peripherals run.**  Same
   code laptop or fleet — only the transport changes (`inproc://`
   → `tcp://` when nodes move across boards).

See [`dev/docs/history/ROADMAP_0.4.md`](dev/docs/history/ROADMAP_0.4.md) for the
full track breakdown.

### How JROS fits next to ROS and Hermes

| | **ROS 2** | **Hermes / agent frameworks** | **JROS** |
|---|---|---|---|
| Embodied robotics | ✅ industry standard | ❌ doesn't think about bodies | ✅ Mac → Jetson → Teensy → ESP32 first-class |
| Local LLM agent | ❌ no agent layer | ❌ assumes cloud | ✅ Gemma local, no internet needed |
| Mac-native dev | ❌ Linux + Docker | ✅ runs on Mac | ✅ Mac-first since 0.2 |
| Transport weight | ❌ DDS (~2 GB install) | n/a (single process) | ✅ ZMQ (50 KB) |
| Learning curve | hard | easy | medium — one Python file per node |
| One-Mac development | painful | easy | ✅ monolithic mode = same code, no IPC |
| Multi-board production | ✅ designed for it | ❌ no | ✅ flip a config flag |
| Operator UX out of the box | ❌ build your own | n/a | ✅ TUI + (Track F) web inspector |
| Crash isolation per subsystem | ✅ best | ❌ none | ✅ per node when split |

**The pitch in one line:** the only framework where a local LLM
agent thinks and a dedicated set of hardware nodes act — designed
for one developer driving one robot from a Mac.

---

## Reference Jaegers

| Jaeger | Form | Role |
|---|---|---|
| **Lilith** | Digital — local LLM with adjustable personality, runs on Mac | First JROS-native agent — proves the `jaeger-os` agent layer before JP01 inherits it. |
| **JP01** | Drone — Mac + Jetson + Teensy + ESP32 + LED panel + servos + cameras + mics | First hardware Jaeger — inherits Lilith's agent unchanged, adds hardware middleware. |

The strategy is **agent first, body second**: Lilith proves the brain in
software, then JP01 puts a body around the same brain. A new Jaeger is a
config file plus a logic node — not a fork of the runtime.

---

## Repo Layout

```
JROS/                       ← clone goes here (default ~/jaeger)
├── install.sh              ← venv + deps; safe to re-run
├── run.sh                  ← launcher
├── requirements.txt        ← runtime deps (installed into .venv)
├── scripts/install.sh      ← curl one-liner target (user-facing)
├── jaeger_os/              ← framework code (git-tracked)
│   ├── run.py, main.py     ← entry points
│   ├── core/, cli/, plugins/, skills/, prompts/, assets/, interfaces/
│   ├── migrations/         ← per-version migration scripts
│   └── models/             ← downloaded GGUF weights (gitignored except README)
├── .jaeger_os/             ← operator state (gitignored)
│   ├── instances/<name>/   ← each agent's full state, one folder per agent
│   ├── models/             ← shared model cache
│   ├── backups/            ← `jaeger backup` output
│   └── jaeger.env          ← sourceable instance pin
├── dev/docs/               ← architecture + design notes
├── dev/tests/              ← framework test suite
├── dev/benchmark/          ← bench corpus + sweep + sanity probe
├── dev/scripts/            ← dev_env.sh, run_tests.sh, generators
├── sandbox/                ← in-repo isolated test install (gitignored)
├── pyproject.toml          ← pytest + ruff config
├── README.md, CHANGELOG.md, LICENSE
└── .git/, .gitignore
```

Two clear buckets at the install root: `jaeger_os/` (framework, owned
by upstream) and `.jaeger_os/` (operator state, gitignored). `jaeger update`
only touches the first; instance memory/logs/credentials survive every
upgrade.

---

## Benchmarking the agent locally

JROS ships **two benchmark types** under `dev/benchmark/`:

- **`bench.py` — the routing corpus.** The 81-case suite that measures
  tool-routing / planning quality (E4B **79/81**, the all-time high; 26B
  75–76). This is the **hard gate**: any change to the agentic pipeline must
  hold ≥79/81. Fast, no live-instance side effects.
- **`scenarios.py` — the hermetic scenario suite.** 51 full-system cases (36
  scriptable + 15 security gates), each run against a throwaway temp instance
  so a run can never pollute live state. Multi-turn, exercises real tools,
  memory, and scheduling end-to-end. A **security-gate failure exits non-zero**
  (`--lane security` runs just those; `--list` lists cases without booting a
  model; `--model-path <gguf>` runs the suite on a different model, e.g. the
  26B for a final validation).

Security posture (0.7.0): **14/15 on the default 4B, 15/15 on the 26B** — the
one 4B gap (memory-poisoning) is fixed by model scale and gated behind the
permission layer regardless.

---

## Documentation

| Doc | What |
|---|---|
| [`dev/docs/README.md`](dev/docs/README.md) | Where everything lives — the doc map |
| [`dev/docs/reality/system_runtime_user.md`](dev/docs/reality/system_runtime_user.md) | Three-layer architecture — System / Runtime / User |
| [`dev/docs/reality/agentic_runners.md`](dev/docs/reality/agentic_runners.md) | The two runners (realtime + Deep Think) + inference lanes |
| [`dev/docs/reality/memory_architecture.md`](dev/docs/reality/memory_architecture.md) | Subject-attributed SQL memory (provenance + history) |
| [`dev/docs/reality/skill_standard.md`](dev/docs/reality/skill_standard.md) | The self-authored skill standard |
| [`dev/docs/reality/scenario_bench.md`](dev/docs/reality/scenario_bench.md) | The hermetic scenario benchmark |
| [`dev/docs/vision/framework_vision.md`](dev/docs/vision/framework_vision.md) | The 0.8 modular-framework north star |
| [`dev/docs/revision_summaries/`](dev/docs/revision_summaries/) | Per-release write-ups (0.1 → 0.7) |

The full JROS spec — architecture, transport, the node standard, the agent
and skill systems — continues to land under `dev/docs/`.

---

## Roadmap

- **0.1 — Agent layer.** Local-first agent, self-authored skills, the
  `computer_use` skill, the kanban task board, Deep Think, the external-model
  pipeline. ✅ *shipped*
- **0.4 — Node standard.** ZMQ + UDP transport, the node/plugin contract, the
  body contract, the first nodes. ✅ *shipped*
- **0.5 — Character system + Studio.** The Mochi fold-in: characters,
  animation/media nodes, the Jaeger Studio GUI (since extracted). ✅ *shipped*
- **0.6 — Product shell.** One-command install, in-place update/rollback,
  lifecycle, the agentic-quality arc. ✅ *shipped*
- **0.7 — Swift-first + two-runner core.** `JaegerOS.app`, the versioned
  bridge, the measured realtime + Deep Think runners, dual-context inference
  lanes, the identity/character split, and the scenario benchmark.
  ✅ *shipped*
- **0.8 — Modular framework.** Modules (TTS/STT/vision/hardware nodes,
  plugins) that own their own config/settings/lifecycle and register into a
  unified surface — the ROS2-style federation seam
  ([`dev/docs/vision/framework_vision.md`](dev/docs/vision/framework_vision.md)).
- **JP01.** The first hardware Jaeger — the same brain, a body around it.

---

## Community

Built in the open by **[Jenkins Robotics](https://jenkinsrobotics.github.io)**.

**Follow** — [Discord](https://discord.gg/sAnE5pRVyT) ·
[YouTube](https://www.youtube.com/@Jenkins_Robotics) ·
[Instagram](https://www.instagram.com/jenkinsrobotics/) ·
[Facebook](https://www.facebook.com/jenkinsrobotics/)

**Support** — [Patreon](https://www.patreon.com/JenkinsRobotics) ·
[Venmo](https://venmo.com/u/JenkinsRobotics)

---

## License

[Apache-2.0](LICENSE) © Jenkins Robotics
