# 🗺️ JaegerAI Architecture & Directory Guide

> **A Plain-English Guide for Developers and Non-Coders**  
> This document explains how `JaegerAI` is organized, where each feature lives, and how to find and edit code easily.

---

## 🧭 "Where Do I Find...?" Quick Lookup

| I want to... | Where do I look? | Key files |
| :--- | :--- | :--- |
| **Edit the Web UI (look & feel, branding, chat page)** | [`jaeger_ai/features/webui/`](file:///Users/matthewjenkins/GitHub/JaegerAI/jaeger_ai/features/webui/) | `static/jaeger_webui_branding.js`, `adapter/server.py`, `service/profile_layout.py` |
| **Edit the Task Dispatcher & Kanban board** | [`jaeger_ai/features/dispatcher/`](file:///Users/matthewjenkins/GitHub/JaegerAI/jaeger_ai/features/dispatcher/) | `store.py`, `router.py`, `sidecar.py`, `static/jaeger_dispatcher.js` |
| **Edit Roundtable (multi-agent debate & consensus)** | [`jaeger_ai/features/roundtable/`](file:///Users/matthewjenkins/GitHub/JaegerAI/jaeger_ai/features/roundtable/) | `policy.py` (rules), `service.py` (engine), `roundtable.py` (streaming) |
| **Add or edit Agent Tools (FastMCP tools)** | [`jaeger_ai/features/host_capabilities/`](file:///Users/matthewjenkins/GitHub/JaegerAI/jaeger_ai/features/host_capabilities/) | `server.py`, `tools/` (file, shell, search, app tools) |
| **Edit Shared Memory (Honcho)** | [`jaeger_ai/features/shared_memory/`](file:///Users/matthewjenkins/GitHub/JaegerAI/jaeger_ai/features/shared_memory/) | `honcho_client.py` |
| **Change CLI commands (`jaeger start`, `stop`, `bench`)** | [`jaeger_ai/cli/verbs/`](file:///Users/matthewjenkins/GitHub/JaegerAI/jaeger_ai/cli/verbs/) | `lifecycle_verbs.py`, `dispatch.py` (CLI arg router) |
| **Run diagnostic / verification scripts** | [`scripts/`](file:///Users/matthewjenkins/GitHub/JaegerAI/scripts/) | `run-host-capability-server.py`, `verify-*.py` |

---

## 🏛️ Top-Level Directory Layout

```text
JaegerAI/
├── apps/                       # 📱 Decoupled Frontend Applications (OpenClaw-parity layout)
│   ├── macos/                  # Native macOS SwiftUI / AppKit application
│   └── web/                    # Browser-based web client and dashboard
├── packages/                   # 📦 Decoupled, standalone Python packages
│   ├── jaeger-agent/           # Lightweight autonomous agent package
│   ├── jaeger-os/              # Jaeger OS abstractions and daemon logic
│   ├── jaeger-kokoro-tts/      # Text-to-speech audio synthesis package
│   └── jaeger-whisper-stt/     # Speech-to-text audio transcription package
├── jaeger_ai/                  # 🧠 The primary Jaeger AI application source code
│   ├── core/                   # Core brain: memory, sessions, diagnostics, settings, models
│   │   ├── gateway/            # 🚪 Unified Gateway Daemon & persistent SQLite session bus
│   │   └── runtime/            # ⚡ Autonomous loop, dispatcher, and tool-call repair
│   ├── features/               # 🌟 Self-contained feature modules (Web UI, Dispatcher, Roundtable, etc.)
│   │   ├── webui/              # 🌐 Web UI adapter, service, branding, and runners
│   │   ├── dispatcher/         # 📋 Task Kanban board, worker routing, and SQLite persistence
│   │   ├── roundtable/         # 🏛️ Multi-agent debate orchestrator (Jaeger, Hermes, OpenClaw)
│   │   ├── host_capabilities/  # 🛠️ 29 FastMCP tools for host interaction (files, terminal, apps)
│   │   ├── shared_memory/      # 🧠 Shared memory substrate (Honcho client)
│   │   ├── missions/           # 🎯 High-level autonomous mission runners
│   │   ├── knowledge_library/  # 📚 Knowledge indexing and retrieval
│   │   ├── cost_tracking/      # 💰 Token cost and provider usage accounting
│   │   ├── caldav/             # 📅 Calendar synchronization
│   │   └── insta360/           # 📷 Camera and vision peripheral controls
│   ├── cli/                    # 💻 Command-line verb handlers (`start`, `stop`, `status`, `chat`, etc.)
│   ├── interfaces/             # 🔌 System interfaces (A2A server, Swift UI bridge, MCP server, TUI)
│   ├── personality/            # 🎭 Agent character definitions and persona states
│   └── plugins/                # 🧩 Messaging integrations (Discord, Telegram, iMessage, HomeAssistant)
├── scripts/                    # 🔧 Management, verification, and diagnostic shell/python scripts
├── dev/                        # 🧪 Test suites (`dev/tests/`) and developer documentation
├── docs/                       # 📖 User guides and system documentation
└── vendor/                     # 👥 Third-party components (e.g., hermes-webui upstream)
```

---

## 💡 How Modular Features Work

Every feature in `jaeger_ai/features/` is designed to be **self-contained**:
1. **Its own code**: All scripts, endpoints, and logic live inside that feature's directory.
2. **Its own docs**: Contains a beginner-friendly `README.md` explaining what the feature does, how it works, and which files to edit.
3. **Its own tests/verification**: Contains verification scripts or unit test references.

Non-coders and developers can safely work inside a feature folder without worrying about breaking unrelated parts of the system.
