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
  <a href="https://github.com/JenkinsRobotics/JROS/releases"><img src="https://img.shields.io/badge/version-0.2.0-2EA44F?style=for-the-badge" alt="Version"></a>
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
no Docker, no special OS versions, no dependency hell. It is `pip install`
simple; a virtual environment is enough.

- 🧠 **Local-first** — runs entirely on-device on an in-process LLM. No cloud account required.
- 🛠️ **~70 built-in tools across 11 toolset categories** — files (read / write / edit / search), memory, web, code execution, scheduling, background processes, kanban, delegation. A 20-tool CORE is always visible; the rest are reachable via `describe_tool` / `load_toolset` when scoping is enabled.
- 📋 **Kanban task board** — the agent plans multi-step work as cards; Deep Think jobs live on the same board. `/board` to view it.
- 📚 **Self-authored skills** — the agent researches, writes, smoke-tests, benchmarks, and versions its own skills.
- 🖥️ **Computer use** — the flagship skill: drive any macOS app through the accessibility tree (see the screen, click, type, work menus).
- 🌙 **Deep Think** — an idle "deep sleep" mode that swaps to a heavier coder model and drains a skill-development queue.
- 🔌 **Model-agnostic** — opt into LM Studio, an OpenAI-compatible endpoint, or Anthropic Claude. Local stays the default.
- 🔒 **6-tier permission ladder** — every tool is gated; high-risk actions are confirmation-prompted and audit-logged.
- 🤖 **Embodiment-ready** — the body contract and the capability-gated skill loader are already in place for hardware.

> **Status — `0.2.0` released.** Refinement + Jaeger-port-enablement
> cycle. Adds the **sleep-cycle architecture** (awake/asleep model
> swap with a 1-hour inactivity timer — see
> [`docs/deep_think_design.md`](docs/deep_think_design.md)) and a
> **memory-tier-aware setup wizard** that detects the host's unified
> RAM and recommends data-validated awake + asleep model pairs (12 /
> 24 / 32 / 64+ GB ladders). Bench corpus bumped to **v1.1** (59 cases
> with new T1c hallucination, T3 cross-turn, T5 safety tiers) —
> rankings refreshed against the new corpus and persisted in
> [`benchmark/HISTORY.md`](benchmark/HISTORY.md). Next major beat:
> **hardware-node layer** (transport, motors, LEDs) on JP01.

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

**Recommended — install with [pipx](https://pipx.pypa.io/):**

```bash
pipx install jaeger-os         # isolated venv, `jaeger` on PATH
jaeger setup                   # interactive wizard — identity, model, voice
jaeger start                   # boot the daemon
jaeger rich-tui                # talk to the agent
```

pipx gives each app its own virtual environment, so JROS's heavy
native deps (llama-cpp, kokoro, whisper) don't fight with whatever
else lives in your Python. Upgrades are one line:

```bash
pipx upgrade jaeger-os         # framework upgrade
jaeger update                  # follow up: backs up + migrates your instances
```

**Or with plain pip:**

```bash
pip install jaeger-os          # works, but pollutes your global / current env
```

A plain install (either way) pulls the **entire** runtime — local
LLM, Kokoro TTS, Whisper STT, vision, the external-model pipeline,
messaging bridges. Nothing is left behind an extra. First launch
runs a short setup wizard (identity, config, model); a GGUF model
is fetched from Hugging Face on first run, and nothing else phones
home.

**State lives at `~/.jaeger/instances/<name>/`** — never inside the
framework install. You can `jaeger backup` an instance, move to a
new machine, `pipx install jaeger-os`, `jaeger restore <archive>`,
and pick up where you left off. See
[docs/instance_layout.md](docs/instance_layout.md) for the full
layout.

**From source (contributors):**

```bash
git clone https://github.com/JenkinsRobotics/JROS.git
cd JROS
pip install -e ".[dev]"        # editable install for development
pytest
```

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
JROS/
├── src/jaeger_os/    the framework package  →  pip install jaeger-os
├── tests/            the framework test suite
├── docs/             framework documentation
├── benchmark/        bench corpus + sweep + sanity probe (dev tooling)
├── pyproject.toml    packaging — jaeger-os 0.2.0
├── README.md         this file
└── LICENSE           Apache-2.0
```

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
| [`docs/external_models.md`](docs/external_models.md) | Running the agent on LM Studio / OpenAI / Anthropic Claude |
| [`docs/deep_think_design.md`](docs/deep_think_design.md) | Deep Think — the idle skill-development mode |
| [`docs/marketplace_spec.md`](docs/marketplace_spec.md) | The skill marketplace |
| [`docs/physical_skills_status.md`](docs/physical_skills_status.md) | Where embodiment / physical skills stand |
| [`docs/kanban_design.md`](docs/kanban_design.md) | The kanban task board |
| [`docs/hermes_tool_parity.md`](docs/hermes_tool_parity.md) | Tool-surface audit vs. Hermes Agent |
| [`docs/BENCHMARK_0.1.0.md`](docs/BENCHMARK_0.1.0.md) | 0.1.0 full verification benchmark |

The full JROS spec — architecture, transport, the node standard, the agent
and skill systems — is being written and will land under `docs/`.

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
