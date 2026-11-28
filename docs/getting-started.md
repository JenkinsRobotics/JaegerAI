# Getting Started with JaegerAI

JaegerAI supports two install tracks:

1. **Jaeger Core (Portable, Cross-Platform):** macOS (Apple Silicon & Intel), Linux, and Windows x64 — no Node.js, MLX, or Xcode required.
2. **Full macOS Stack (Source Checkout):** Full 32 GB Apple Silicon platform with native macOS integrations, MLX Kokoro TTS / Whisper STT, Droid Mode, and optional NexusUI VRM shell.

---

## Option A: Jaeger Core (macOS, Linux & Windows)

### Prerequisites
- **macOS** (Apple Silicon or Intel), **Linux**, or **Windows x64**
- **Python 3.11 or 3.12** (with internet access for initial third-party Python wheel install)

### Install & Launch
1. Download `jaeger-core-1.0.1.zip` from [GitHub Releases](https://github.com/JenkinsRobotics/JaegerAI/releases/latest) and extract it.
2. Run the installer in the extracted folder:
   - **macOS / Linux:** `python3 install-core.py`
   - **Windows (PowerShell):** `py -3.12 install-core.py`
3. Run the exact launch command printed by the installer (for example `"~/.jaeger/core-venv/bin/python" -m jaeger_ai core` on macOS/Linux, or `& "$env:USERPROFILE\.jaeger\core-venv\Scripts\python.exe" -m jaeger_ai core` on Windows).
4. Open **http://127.0.0.1:8790** in your browser and configure a local ([Ollama](https://ollama.com)) or cloud model.

Every fresh Core install starts with a **neutral owner profile**, isolated data under `~/.jaeger/core`, and zero pre-existing chats or credentials. Set `JAEGER_WORKSPACE` to an existing folder to choose your workspace directory.

---

## Option B: Full macOS / Linux Source Checkout

### Prerequisites
- macOS (Apple Silicon recommended for MLX voice & 32 GB unified memory) or Linux
- Python **3.11 or 3.12**
- Node.js **20+** (for building the React 19 Studio WebUI)
- Optional local models: [Ollama](https://ollama.com)

### 1. Install (One Command)

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

### 2. Verify Installation

```bash
./jaeger doctor
```

### 3. Start & Use JaegerAI

```bash
# Terminal 1: Start the standalone Gateway (:33418) + Studio WebUI (:8790)
./jaeger start

# Terminal 2: Chat directly in your terminal (streaming TUI)
./jaeger

# Or open the 5-Tab Studio WebUI + On-Screen VR Avatar in your browser
./jaeger open
```

### 4. Configure Your Personal Counterpart

Open **Control & Body** in the WebUI (or call `PUT /v1/identity`) to set your own AI name, owner name, avatar (`.vrm` / `.glb` / 2D), voice, and connected MCP servers (`~/.jaeger/mcp_servers.json`).
