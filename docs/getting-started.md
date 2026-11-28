# Getting Started with JaegerAI

## Prerequisites

- macOS (Apple Silicon recommended, 32 GB unified memory supported out of the box) or Linux
- Python **3.11 or 3.12**
- Node.js **20+** (for building the 5-Tab Studio React 19 WebUI)
- Optional local models: [Ollama](https://ollama.com) (`gemma4:12b`, `qwen3-vl:8b`, etc.)

## 1. Install (One Command)

```bash
git clone https://github.com/JenkinsRobotics/JaegerAI.git
cd JaegerAI
./install.sh --profile full
```

Available profiles:
- `core` — Core cognitive loop, memory, tools, MCP, avatar, Gateway & WebUI
- `business` — Core + 8-role autonomous business team, YouTube Studio & Channels
- `companion` — Core + Kokoro MLX TTS, Whisper STT, realtime voice, vision & headless Minecraft
- `droid` — Companion + Host Droid Mode (gimbal camera/mic/speakers) & JP01 hardware
- `full` — Everything (default)

## 2. Verify Installation

```bash
./jaeger doctor
```

## 3. Start & Use JaegerAI

```bash
# Terminal 1: Start the standalone Gateway (:33418) + Studio WebUI (:8790)
./jaeger start

# Terminal 2: Chat directly in your terminal (streaming TUI)
./jaeger

# Or open the 5-Tab Studio WebUI + On-Screen VR Avatar in your browser
./jaeger open
```

## 4. Configure Your Personal Counterpart

Open **Control & Body** in the WebUI (or call `PUT /v1/identity`) to set your own AI name, owner name, avatar (`.vrm` / `.glb` / 2D), voice, and connected MCP servers (`~/.jaeger/mcp_servers.json`).
