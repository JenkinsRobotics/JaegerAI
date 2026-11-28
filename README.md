<h1 align="center">JaegerAI</h1>

<p align="center">
  <strong>A persistent, asynchronous, event-driven cognitive platform — cross-platform Jaeger Core &amp; full 32 GB Apple Silicon stack</strong><br>
  <em>Conversation is an interface to the intelligence, not its execution loop.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.1-0A84FF?style=for-the-badge" alt="Version 1.0.1">
  <img src="https://img.shields.io/badge/license-Apache--2.0-2EA44F?style=for-the-badge" alt="Apache-2.0">
  <img src="https://img.shields.io/badge/platforms-macOS%20%7C%20Linux%20%7C%20Windows-5B8DEF?style=for-the-badge" alt="macOS | Linux | Windows">
  <img src="https://img.shields.io/badge/python-3.11--3.12-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11-3.12">
  <img src="https://img.shields.io/badge/react-19%20%2B%20Three.js%20VRM-61DAFB?style=for-the-badge&logo=react&logoColor=black" alt="React 19 + VRM">
</p>

---

## Core Architecture

JaegerAI is a **100% modular, one-command reproducible AI platform** built with **zero external infrastructure daemons** (no Redis, Postgres, RabbitMQ, Docker, or Electron — pure embedded **SQLite WAL + in-process `asyncio`** + static Vite React 19 UI).

Every capability lives in an independently testable standalone package under `packages/`:

| Layer | Standalone Packages | Purpose |
|---|---|---|
| **Core Spine & Contracts** | `jaeger-contracts`, `jaeger-events`, `jaeger-reliability`, `jaeger-models` | Zero-dep `Protocol` ports (incl. `EmbodimentPort`), streaming Ollama/OpenAI/Anthropic providers, multi-modality Hardware-Fit Cookbook (`hwfit`), blind/consensus `ModelRoundtable`, prompt-cache collapse detection |
| **Authority & Security** | `jaeger-authority`, `jaeger-skills`, `jaeger-mcp`, `jaeger-checkpoints` | Fail-closed policy engine, macOS Seatbelt `.sbpl`/`.sb` & `.toml` sandbox profiles, secret redaction (`redact_text`), Skills Guard AST auditor + external agent importer, live MCP 2.x client with 1-click presets (`aether_studio`, `jaeger_arena`, `rea`) |
| **Cognition & Memory 2.0** | `jaeger-cognition`, `jaeger-memory`, `jaeger-loop`, `jaeger-orchestration` | 24/7 `CognitiveLifeLoop` + SQLite WAL `WorldModelStore`, dual `BUILD`/`PLAN` execution modes, durable `SqlitePregelCheckpointer`, `DeepResearchEngine` (cited Markdown + Visual HTML reports), SQLite WAL `KanbanBoard` & one-shot `OneShotReminderStore`, 32 GB `ResourceGovernor`, Memory 2.0 cascading forget & multi-day persistent goals |
| **Autonomous Business & Studio** | `jaeger-business`, `jaeger-youtube`, `jaeger-channels` | 8-role autonomous business team with spend caps & mandatory owner approval gates; phased 32 GB YouTube Research + Episode Studio; Discord ambient room buffer, mention gating & bot-loop protection |
| **24/7 Presence & Embodiment** | `jaeger-kokoro-tts`, `jaeger-whisper-stt`, `jaeger-realtime`, `jaeger-vision`, `jaeger-droid`, `jaeger-embodiment-minecraft`, `jaeger-hardware` | Apple Silicon MLX Kokoro TTS (`lip_marks()` visemes), Whisper STT, `<ignore>`/`<reply>` LLM ambient speech gate + self-speech echo filter + first-comma chunking + barge-in, rolling-pruned camera buffer, Droid Mode, headless Mineflayer Minecraft co-op, JP01 hardware (`EStopLatch` + bracket protocol), and fail-closed `NexusStationBridge` for NexusUI hardware workbenches |
| **Avatar, Virtual Office & Studio UI** | `jaeger-avatar`, `@jaeger/ui-protocol`, `@jaeger/ui-sdk`, `@jaeger/ui-kit`, `@jaeger/ui-avatar`, `@jaeger/ui-office`, `@jaeger/ui-features` | Canonical `avatar/v1` pack discovery, 2D/3D VRM 0.x/1.0 avatar stage (3-point studio lighting, relaxed stance, AutoBlink, eye saccades, Kokoro viseme lip-sync), interactive 2D pixel Virtual Office + live Minecraft terrain peek, OpenCode Patchmark streaming Markdown, multi-track `StudioTimeline`, Context X-Ray, `Cmd+K` palette |
| **Evals, macOS & Interop** | `jaeger-evals`, `jaeger-protocols`, `jaeger-tools`, `jaeger-browser`, `jaeger-lsp`, `jaeger-macos`, `jaeger-gateway` | `SpanTree` trajectory evals, retained evidence handle paging, domain-guarded browser vault & site gotchas, native Apple Mail / Calendar / Reminders / Notes + sensitive-app computer-use guard, standalone `aiohttp` Gateway with OpenAI-compatible `/v1/chat/completions`, SSE event spine, and zero-dep `JaegerClient` Python SDK |

---

## Jaeger Core (macOS Apple Silicon & Intel, Linux, Windows x64)

Core runs the same Gateway, chat, memory, Authorized Task Handling, model telemetry/risk cards, and 5-Tab WebUI without the native Mac app, MLX, or Node.js on the target machine. Download the release ZIP from [GitHub Releases](https://github.com/JenkinsRobotics/JaegerAI/releases/latest) (requires Python 3.11 or 3.12 and network access for initial Python dependency installation).

| Platform | Install Command (after extracting `jaeger-core-1.0.1.zip`) |
|---|---|
| **macOS (Apple Silicon & Intel)** | `python3 install-core.py` |
| **Linux (x64 / arm64)** | `python3 install-core.py` |
| **Windows (x64 PowerShell)** | `py -3.12 install-core.py` |

1. Download and extract `jaeger-core-1.0.1.zip` from [GitHub Releases](https://github.com/JenkinsRobotics/JaegerAI/releases/latest).
2. Run the platform installer command above.
3. Run the exact launch command printed by the installer, then open **http://127.0.0.1:8790**. Configure an available local (Ollama / llama.cpp) or cloud model in the WebUI.

Core binds to localhost and stores its data in `~/.jaeger/core` by default.
Each fresh installation starts with a neutral owner profile and its own
local chat and memory stores. Cloning this repo or installing Core does not
copy another installation's state or credentials.
Set `JAEGER_WORKSPACE` to an existing folder to use it as your working directory.
Host shell, Python snippets, PTY, and native Apple/Droid hardware controls are
not part of the portable profile. Use the full Mac setup below for those tools.

For contributors, build the same ZIP from a Git checkout with
`python scripts/build-core.py --output <directory>` (requires npm, setuptools, and wheel).
The build stages only tracked product source and builds a fresh WebUI.
To run Core directly from a POSIX checkout, use
`./install.sh --profile core` followed by `./jaeger core`.

## Full macOS Setup

```bash
git clone https://github.com/JenkinsRobotics/JaegerAI.git
cd JaegerAI

# One-command reproducible install (profiles: core | business | companion | droid | full)
./install.sh --profile full

# Verify packages, binaries, WebUI & live Gateway
./jaeger doctor

# Launch standalone Gateway (:33418) + 5-Tab Studio WebUI (:8790)
./jaeger start
./jaeger open

# Or chat directly from the terminal
./jaeger                  # Interactive streaming TUI
./jaeger ask "status?"    # Single-turn prompt
```

Open **http://127.0.0.1:8790** for the 5-Tab Studio UI (`Command`, `Work & Studio`, `Team & Tools`, `Memory & Life`, `Control & Body`) with the live dockable **VR Avatar & Mind Drawer**.

---

## 32 GB Unified Memory 24/7 Discipline

JaegerAI enforces a hard 3-tier priority scheduler (`jaeger_orchestration.ResourceGovernor`) so a single 32 GB Apple Silicon machine can stay aware 24/7 while doing real work:

1. **Tier 1 — `OWNER_WORK` (Highest):** Instant preemption of idle background tasks; reserves the single heavy model slot (LLM *or* VLM, never both simultaneously).
2. **Tier 2 — `AWARENESS_SAFETY`:** Lightweight 24/7 Kokoro MLX TTS, Whisper STT, rolling-pruned camera frames (max 6 resident frames), and hardware/software E-Stop latch.
3. **Tier 3 — `IDLE_LIFE`:** When the owner is away and RAM headroom is healthy, Jaeger autonomously pursues multi-day persistent goals (e.g., headless Mineflayer Minecraft at ~150 MB RAM / 0 GPU) and saves an instant SQLite WAL checkpoint the millisecond owner work arrives.

---

## Verification

Run the entire standalone backend + AST package layering + repo hygiene + frontend Vitest + theme-token + TypeScript + external Vite build suite with one command:

```bash
./jaeger verify
```

---

## License & Attributions

JaegerAI is licensed under the **Apache License 2.0**. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for attributions to all permissively licensed MIT and Apache-2.0 open-source components incorporated into our modular packages.
