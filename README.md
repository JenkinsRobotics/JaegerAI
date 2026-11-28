<h1 align="center">JaegerAI</h1>

<p align="center">
  <strong>A persistent, asynchronous, event-driven cognitive platform — local-first on 32 GB Apple Silicon</strong><br>
  <em>Conversation is an interface to the intelligence, not its execution loop.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.0-0A84FF?style=for-the-badge" alt="Version 1.0.0">
  <img src="https://img.shields.io/badge/license-Apache--2.0-2EA44F?style=for-the-badge" alt="Apache-2.0">
  <img src="https://img.shields.io/badge/python-3.11--3.12-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11-3.12">
  <img src="https://img.shields.io/badge/react-19%20%2B%20Three.js%20VRM-61DAFB?style=for-the-badge&logo=react&logoColor=black" alt="React 19 + VRM">
  <img src="https://img.shields.io/badge/memory-32GB%20Unified%20Budget-5B8DEF?style=for-the-badge" alt="32GB Budget">
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

## Quick Start (One-Command Reproducible Setup)

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
