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
  <a href="https://github.com/JenkinsRobotics/JROS/releases"><img src="https://img.shields.io/badge/version-0.5.2-2EA44F?style=for-the-badge" alt="Version"></a>
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
- 🛠️ **~70 built-in tools across 11 toolset categories** — files (read / write / edit / search), memory, web, code execution, scheduling, background processes, kanban, delegation. A 20-tool CORE is always visible; the rest are reachable via `describe_tool` / `load_toolset` when scoping is enabled.
- 📋 **Kanban task board** — the agent plans multi-step work as cards; Deep Think jobs live on the same board. `/board` to view it.
- 📚 **Self-authored skills** — the agent researches, writes, smoke-tests, benchmarks, and versions its own skills.
- 🖥️ **Computer use** — the flagship skill: drive any macOS app through the accessibility tree (see the screen, click, type, work menus).
- 🌙 **Deep Think** — an idle "deep sleep" mode that swaps to a heavier coder model and drains a skill-development queue.
- 🔌 **Model-agnostic** — opt into LM Studio, an OpenAI-compatible endpoint, or Anthropic Claude. Local stays the default.
- 🔒 **6-tier permission ladder** — every tool is gated; high-risk actions are confirmation-prompted and audit-logged.
- 🤖 **Embodiment-ready** — the body contract and the capability-gated skill loader are already in place for hardware.

> **Status — `0.3.0` released.** Voice pipeline rebuild + skill
> system v3 + persona prefill. The 0.2.x in-process Rich TUI stays
> as the operator surface; the 0.3.0 work layers underneath it:
>
> - **Persistent TTS output stream** — one long-lived OutputStream
>   opens at warm time, stays alive for the session.  Two backends,
>   config-toggled via `config.voice.audio_backend`:
>     - `sounddevice` (default) — PortAudio, with the output device
>       resolved LIVE via CoreAudio so it follows Settings → Sound.
>     - `avaudio` — PyObjC AVAudioEngine, direct
>       `scheduleBuffer:completionHandler:` (no PortAudio in the loop).
> - **Skill system v3** — unified `jros.skill/v3` manifest schema
>   (id, version, origin, package, runtime, domains, embodiment,
>   permissions, capabilities with per-capability scoring bands +
>   levels, dependencies, artifacts, entrypoint, body, provenance).
>   Capability state persists in `<instance>/capabilities/`; promotion
>   /demotion rules update the live band the router consults.
> - **Persona prefill** — wizard-time YAML templates in
>   `jaeger_os/personas/` prefill `identity.yaml` + `soul.md` when a
>   new instance is created.  Zero runtime cost on existing instances.
> - **Whisper STT hardening** — `is_non_speech_marker()` suppresses
>   `[BLANK_AUDIO]` / `(beep)` / `[music]` in follow-up + no-wake-word
>   modes.  Optional AEC plumbing on `_MicStream`.
> - **Gemma 4 12B-it Q4** added to the model registry; promoted to the
>   24 GB tier asleep pick (Mac Mini sweet spot — leaderboard #1 at
>   94.9 % routing on the 2026-06-04 bench).
> - **`./launch`** — sandbox launcher with a real-verification boot
>   scroll (every row a check the launcher actually performs against
>   the instance bundle).  Housekeeping flags: `--status`, `--stop`,
>   `--restart`, `--reset-audio`, `--clean-logs`, `--health`.
>
> See `CHANGELOG.md` for the full entry and the explicit "Skipped
> from the upstream 0.3.0 plan" list. The Swift desktop app stays in
> tree as archived code. The multi-process daemon scaffold was removed
> 2026-06-14 when JROS converged on fused mode; the `rich_tui` surface
> is parked in tree (GUI design preserved) for the windowed-app
> rework — neither is wired into install or run yet.

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
./jaeger agent create    # create your first agent — the wizard picks a
                         # character, memory tier, model, and voice.
./jaeger                 # launch the default agent
```

`jaeger` is the one operator command. Add `~/jaeger` to your `PATH` (the
installer prints the exact line) to drop the `./` and run `jaeger` from
anywhere; `./run.sh` still works as an alias.

Or scaffold a named agent:

```bash
./jaeger agent create lilith  # create "lilith" via the wizard
./jaeger --agent lilith       # launch "lilith"
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
never touch it. See [`dev/docs/architecture/system_runtime_user.md`](dev/docs/architecture/system_runtime_user.md)
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

## Daily use

`jaeger` (or `./jaeger` from the install dir) is the operator surface — it
boots the agent app; `--tui` runs it in the terminal instead. Pick whichever
launch path matches what you're doing.

**Run a named agent** — the production flow:

```bash
./jaeger --agent lilith            # launch the 'lilith' agent
./jaeger --agent lilith --no-voice # text-only (no mic, no Kokoro warm)
```

**Sandbox dev loop** — for working on JROS itself.  The `./launch`
wrapper boots the in-repo sandbox at `sandbox/.jaeger_os/instances/jros-dev/`
with a real-verification boot scroll, then hands the terminal to the
TUI.  Daily flags:

```bash
./launch                           # boot the sandbox TUI
./launch --status                  # what's running across modes
./launch --stop                    # kill a lingering TUI singleton
./launch --restart                 # stop, then boot
./launch --health                  # preflight checks and exit
./launch --reset-audio             # sudo killall coreaudiod
./launch --clean-logs              # truncate <instance>/run/jaeger.log
./launch --no-voice                # tell the TUI to skip voice startup
```

The `./launch` boot scroll runs every check before handing off:
sandbox bundle, library import resolution, instance manifest schema,
GGUF model on disk, AVAudioEngine bridge import, Whisper assets,
Kokoro package, skill registry walk, TUI module import.  A red row
stops boot with the actual reason.

**Pick the audio backend** — 0.3.0 ships two persistent-stream backends
for TTS.  Configure once in your instance's `config.yaml`:

```yaml
voice:
  audio_backend: sounddevice    # PortAudio (default; macOS Settings-default device live-resolved)
  # or:
  # audio_backend: avaudio       # PyObjC AVAudioEngine, direct AVAudioPlayerNode scheduling
```

Or override per-run without editing the config:

```bash
JAEGER_AUDIO_BACKEND=avaudio ./launch
JAEGER_AUDIO_OUTPUT="Mac Studio Speakers" ./launch   # sounddevice device override
```

**Bench against the model registry leaderboard** — runs the full
59-case flat bench and updates `dev/benchmark/HISTORY.md`:

```bash
./dev/benchmark/run_flat_bench.py             # full corpus
./dev/benchmark/run_flat_bench.py --limit 5   # 5-case smoke
./dev/benchmark/run_flat_bench.py --tags routing,multistep
```

The 2026-06-04 leaderboard row for `gemma-4-26B-A4B-it-Q4_K_M` is
**55/59 (93 %)** at `permissions.mode=allow`; bench history is
regenerated on every run.

---

## Architecture direction (0.4+)

**0.3.0 ships the brain.** 0.4.0 wires the spine — the node-based
embodied architecture that turns JROS from a Mac-side agent into a
robot operating framework that drives JP01-class hardware.

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

See [`dev/docs/ROADMAP_0.4.md`](dev/docs/ROADMAP_0.4.md) for the
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

## Benchmarking models locally

JROS ships two complementary benches under `benchmark/` for picking
which local model to run:

- **`run_flat_bench.py` + `run_model_sweep.py`** — *task* benchmark.
  Runs the 59-case corpus (routing, multistep, recovery, multi-turn,
  context, safety, hallucination, cross-turn) per model and writes
  per-run rows + summary under `benchmark/flat/<model>/<ts>/`. The
  sweep auto-runs hybrid thinking models (Qwen3.x, gemma-4) in BOTH
  modes — once with thinking ON, once OFF — so the leaderboard shows
  the deep-think vs direct-mode tradeoff side-by-side.
- **`run_model_sanity.py`** — *hardware-health* benchmark, separate
  from task accuracy. Per model: GPU layer offload + Metal/CPU buffer
  split (did it fully fit?), raw tok/s on a fixed prompt (compare a
  35B-A3B and a 9B on generation speed alone), and for hybrid models
  the think vs direct token-count and wall-clock so you can see what
  reasoning mode actually costs per query.

Useful env knobs (all bench-scoped, default off):

- `JAEGER_BENCH_THINKING=auto|on|off` — force hybrid models into a
  specific mode for a run (cloud-style toggle, same as Claude /
  GPT-o1 / Gemini's `thinking` flag).
- `JAEGER_BENCH_MODEL_TIMEOUT=<seconds>` — per-model wall-clock cap
  for the sweep (default `3600`).
- `JAEGER_BENCH_STALL_S=<seconds>` — per-call stall watchdog (default
  `120`; reasoning models still get bumped to a `300s` floor).

Results aggregate into `benchmark/HISTORY.md` — leaderboard with a
weighted `Score` column (tools / real-time / context / multi-turn /
safety), per-category counts, and safety as a hard gate (any safety
failure → `DQ` regardless of other scores).

---

## Documentation

| Doc | What |
|---|---|
| [`dev/docs/setup.md`](dev/docs/setup.md) | Canonical install, upgrade, and uninstall guide |
| [`dev/docs/architecture/system_runtime_user.md`](dev/docs/architecture/system_runtime_user.md) | Three-layer architecture — System / Runtime / User |
| [`dev/docs/external_models.md`](dev/docs/external_models.md) | Running the agent on LM Studio / OpenAI / Anthropic Claude |
| [`dev/docs/deep_think_design.md`](dev/docs/deep_think_design.md) | Deep Think — the idle skill-development mode |
| [`dev/docs/marketplace_spec.md`](dev/docs/marketplace_spec.md) | The skill marketplace |
| [`dev/docs/physical_skills_status.md`](dev/docs/physical_skills_status.md) | Where embodiment / physical skills stand |
| [`dev/docs/kanban_design.md`](dev/docs/kanban_design.md) | The kanban task board |
| [`dev/docs/hermes_tool_parity.md`](dev/docs/hermes_tool_parity.md) | Tool-surface audit vs. Hermes Agent |

The full JROS spec — architecture, transport, the node standard, the agent
and skill systems — continues to land under `dev/docs/`.

---

## Roadmap

- **0.1 — Agent layer.** Local-first agent, 54 tools, self-authored skills,
  the `computer_use` skill, the kanban task board, Deep Think, the
  external-model pipeline. ✅ *shipped*
- **0.2 — Node standard.** ZMQ + UDP transport, the node/plugin contract,
  the first hardware nodes.
- **0.3 — Lilith.** The first JROS-native digital Jaeger.
- **0.4 — JP01.** The first hardware Jaeger — same brain, a body around it.

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
