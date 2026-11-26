<h1 align="center">JaegerAI</h1>

<p align="center">
  <strong>A persistent, asynchronous, event-driven cognitive platform — local-first on 32 GB Apple Silicon</strong><br>
  <em>Conversation is an interface to the intelligence, not its execution loop.</em>
</p>

<p align="center">
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
| **Core Spine & Contracts** | `jaeger-contracts`, `jaeger-events`, `jaeger-reliability`, `jaeger-models` | Zero-dep `Protocol` ports (incl. `EmbodimentPort`), streaming Ollama/OpenAI/Anthropic providers, Hermes tool schema sanitization, prompt-cache collapse detection |
| **Authority & Security** | `jaeger-authority`, `jaeger-skills`, `jaeger-mcp`, `jaeger-checkpoints` | Fail-closed policy engine, macOS Seatbelt `.sbpl`/`.sb` & `.toml` sandbox profiles, Hermes secret redaction (`redact_text`), Skills Guard AST auditor, live MCP 2.x client |
| **Cognition & Memory 2.0** | `jaeger-cognition`, `jaeger-memory`, `jaeger-loop`, `jaeger-orchestration` | 24/7 `CognitiveLifeLoop` + SQLite WAL `WorldModelStore`, durable `SqlitePregelCheckpointer` with time-travel fork, safe zero-`eval` expressions, Dry-Run simulator, 32 GB `ResourceGovernor` (`OWNER_WORK > AWARENESS_SAFETY > IDLE_LIFE`), Memory 2.0 cascading forget & multi-day persistent goals |
| **Autonomous Business & Studio** | `jaeger-business`, `jaeger-youtube`, `jaeger-channels` | 8-role autonomous business team with spend caps & mandatory owner approval gates; flagship 32 GB single-heavy-model phased YouTube Research + Episode Studio; redacted multi-channel relay |
| **24/7 Presence & Embodiment** | `jaeger-kokoro-tts`, `jaeger-whisper-stt`, `jaeger-realtime`, `jaeger-vision`, `jaeger-embodiment-minecraft`, `jaeger-hardware` | Apple Silicon MLX Kokoro TTS (`lip_marks()` visemes), bus-free Whisper STT (`hearing.py`), `<ignore>/<reply>` voice gate + barge-in, hard-pruned rolling camera buffer, headless Mineflayer Minecraft idle persistence, and JP01 droid hardware (`EStopLatch` + bracket protocol) |
| **Avatar & 5-Tab Studio UI** | `jaeger-avatar`, `@jaeger/ui-protocol`, `@jaeger/ui-sdk`, `@jaeger/ui-kit`, `@jaeger/ui-avatar`, `@jaeger/ui-features` | Grok-grade 2D/3D VRM 0.x/1.0 avatar stage (3-point studio lighting, relaxed stance, AutoBlink, eye saccades, Kokoro viseme lip-sync), OpenCode Patchmark streaming Markdown, OpenReel multi-track `StudioTimeline`, Context X-Ray, `Cmd+K` palette — all unified in 5 calm tabs |
| **Evals & Interop** | `jaeger-evals`, `jaeger-protocols`, `jaeger-tools`, `jaeger-lsp`, `jaeger-macos`, `jaeger-gateway` | `SpanTree` trajectory evals, compaction integrity verifier, AG-UI / A2UI / ACP adapters, standalone `aiohttp` Gateway + WebUI server |

---

## Quick Start (One-Command Reproducible Setup)

```bash
git clone https://github.com/JenkinsRobotics/JaegerAI.git
cd JaegerAI

# Choose a profile: core | business | companion | droid | full
./scripts/setup.sh --profile full

# Verify environment & packages
~/.jaeger/venv/bin/python scripts/doctor.py

# Launch standalone Gateway (:33418) + 5-Tab Studio WebUI (:8790)
~/.jaeger/venv/bin/python -m jaeger_gateway
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

Run the entire standalone backend + AST layering + frontend Vitest + theme-token + TypeScript + external Vite build + no-mock suite with one command:

```bash
./scripts/verify.sh all
```

---

## License & Attributions

JaegerAI is licensed under the **Apache License 2.0**. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for attributions to all permissively licensed MIT and Apache-2.0 open-source components incorporated into our modular packages.
