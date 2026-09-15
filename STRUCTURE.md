# 🗺️ JaegerAI Architecture & Directory Guide

> **A Plain-English Guide for Developers and Non-Coders**  
> This document explains how `JaegerAI` is organized, where each feature lives, and how to find and edit code easily.

---

## 🧭 "Where Do I Find...?" Quick Lookup

| I want to... | Where do I look? | Key files |
| :--- | :--- | :--- |
| **Edit the Web UI (chat page, profiles, adapter)** | [`jaeger_ai/features/webui/`](jaeger_ai/features/webui/) | `adapter/server.py`, `service/profile_layout.py` |
| **Edit the Web UI's look & branding** | [`jaeger_ai/assets/`](jaeger_ai/assets/) | `jaeger_webui_branding.js` — **the only copy**; see below |
| **Edit the Task Dispatcher & Kanban board** | [`jaeger_ai/features/dispatcher/`](jaeger_ai/features/dispatcher/) | `store.py`, `router.py`, `sidecar.py` (board UI: `jaeger_ai/assets/jaeger_dispatcher.js`) |
| **Edit Roundtable (multi-agent debate & consensus)** | [`jaeger_ai/features/roundtable/`](jaeger_ai/features/roundtable/) | `policy.py` (rules), `service.py` (engine), `roundtable.py` (streaming) |
| **Add or edit Agent Tools (FastMCP tools)** | [`jaeger_ai/features/host_capabilities/`](jaeger_ai/features/host_capabilities/) | `server.py`, `grants.py`, `*_tools.py` |
| **Change the agent's persona / tone** | [`jaeger_ai/features/personality/`](jaeger_ai/features/personality/) | `characters/<name>/` (editable YAML — no code needed) |
| **Add/rename a framework, or change a port** | [`jaeger_ai/contract/`](jaeger_ai/contract/) | `frameworks.py`, `ports.py` — the single copy; everything else imports it |
| **Change how a framework runs a turn** | [`jaeger_ai/core/frameworks/`](jaeger_ai/core/frameworks/) | `jaeger.py`, `hermes_native.py`, `openclaw_native.py` |
| **Edit Shared Memory (Honcho)** | [`jaeger_ai/features/shared_memory/`](jaeger_ai/features/shared_memory/) | `honcho_client.py` |
| **Change CLI commands (`jaeger start`, `stop`, `bench`)** | [`jaeger_ai/cli/verbs/`](jaeger_ai/cli/verbs/) | `lifecycle_verbs.py`, `dispatch.py` (CLI arg router) |
| **Run diagnostic / verification scripts** | [`scripts/`](scripts/) | `run-host-capability-server.py`, `verify-*.py` |

---

## 📌 Two rules that explain every exception

Most folders under `jaeger_ai/features/` are exactly one feature: open the
folder, read its `README.md`, and that is the whole thing. Two kinds of file
deliberately sit elsewhere, and knowing which is which saves an afternoon.

**1. Browser extension scripts live in `jaeger_ai/assets/`, not in a feature.**
The Web UI loads one directory as its extension folder
(`HERMES_WEBUI_EXTENSION_DIR`). Three features ship scripts into that single
mount, so the mount owns the directory rather than any one feature.
`jaeger_webui_branding.js`, `jaeger_dispatcher.js` and
`jaeger_gateway_console.js` are all there, and **those are the only copies** —
editing a file anywhere else will not change what the browser loads.

**1b. A fact two layers share lives in `jaeger_ai/contract/`.**
Framework names and service ports are defined there once and imported. If you
find yourself typing `"openclaw"` or `8810` into a second file, that is the
signal — import it instead. `dev/tests/jaeger_ai/contract/` fails if a copy
reappears.

**2. Code used by several features lives under `jaeger_ai/core/`.**
`core/frameworks/` runs a turn against Jaeger, Hermes, OpenClaw or Roundtable.
The Web UI, Roundtable, the Dispatcher and the Gateway all call it, so it belongs
to none of them.

## ⚠️ Three things named "gateway" — which is which

| Path | What it actually is |
| :--- | :--- |
| `jaeger_ai/core/gateway/` | **The Jaeger Gateway.** Owns chat sessions and live events on port 8810. Started by `jaeger gateway daemon`. |
| `jaeger_ai/features/agentgateway/` | Installs and runs the third-party `agentgateway` binary (MCP 8811, A2A 8812). Started by `jaeger gateway start`. |
| `jaeger_ai/interfaces/messaging/` | Discord, Slack and Telegram chat adapters. |

The first two are one CLI word apart and were both called "gateway" until the
second was renamed. If something about sessions is broken, you want the first.

## 🧪 Where the tests are

| Location | Holds |
| :--- | :--- |
| `dev/tests/` | Almost everything. Mirrors the `jaeger_ai/` layout. |
| `<module>/tests/` | Contract tests kept beside the module they check — only under `nodes/` and `plugins/`, where each module carries its own `module.yaml` contract. |
| `packages/<name>/tests/` | Each standalone package tests itself. |

When adding a test, put it in `dev/tests/` unless you are testing a `module.yaml`
contract.

---

## 🏛️ Top-Level Directory Layout

```text
JaegerAI/
├── apps/                       # 📱 Client aliases — SYMLINKS to the real dirs below
│   ├── macos/                  # → jaeger_ai/interfaces/swift
│   └── web/                    # → jaeger_ai/features/webui
├── packages/                   # 📦 Standalone Python packages, each testing itself
│   ├── jaeger-agent/           # The agent loop and model adapters
│   ├── jaeger-os/              # OS abstractions, permissions, daemon logic
│   ├── jaeger-kokoro-tts/      # Text to speech
│   └── jaeger-whisper-stt/     # Speech to text
├── jaeger_ai/                  # 🧠 The main application
│   ├── assets/                 # 🎨 Icons + the browser extension scripts (see rule 1 above)
│   ├── contract/               # 📜 Facts two layers must agree on — imported, never copied
│   ├── core/                   # Shared engine — used by more than one feature
│   │   ├── gateway/            # 🚪 THE Jaeger Gateway: sessions + live events, port 8810
│   │   ├── frameworks/         # 🔀 Runs a turn against Jaeger / Hermes / OpenClaw / Roundtable
│   │   ├── models/             # Model resolution and catalogs
│   │   ├── instance/           # Per-instance config, first boot, personas
│   │   └── runtime/            # Autonomous loop and tool-call repair
│   ├── features/               # 🌟 One folder per feature — each has a README.md
│   │   ├── webui/              # 🌐 Web UI adapter, profiles, session unification
│   │   ├── dispatcher/         # 📋 Task Kanban board and worker routing
│   │   ├── roundtable/         # 🏛️ Multi-agent debate (Jaeger, Hermes, OpenClaw)
│   │   ├── agentgateway/       # 🔌 The third-party agentgateway binary (8811/8812)
│   │   ├── host_capabilities/  # 🛠️ Files, shell, apps, camera, memory — permission-gated
│   │   ├── personality/        # 🎭 The persona used on every turn (YAML characters)
│   │   ├── skill_tree/         # 🌳 XP progression over the agent's skills
│   │   ├── reasoning/          # 💭 Experimental between-turns cognition (off by default)
│   │   ├── timeline/           # 🎬 Multi-track scheduling for avatar performances
│   │   └── …                   # 26 in total — open any one and read its README
│   ├── cli/                    # 💻 Command-line verbs (`start`, `stop`, `webui`, …)
│   ├── interfaces/             # 🔌 Client surfaces ONLY — how a human or peer connects
│   │   ├── swift/              # Native macOS app
│   │   ├── tui/                # Terminal UI
│   │   ├── pyside6/            # Qt desktop UI
│   │   ├── messaging/          # Discord / Slack / Telegram adapters
│   │   └── bridge.py           # The NDJSON socket the native clients speak
│   ├── nodes/                  # 🧩 Manifest-driven modules (each with module.yaml)
│   └── plugins/                # 🧩 Messaging + integration plugins
├── scripts/                    # 🔧 Operator entry points and verify-* diagnostics
├── dev/                        # 🧪 dev/tests/ (the test suite) and developer docs
├── docs/                       # 📖 User and system documentation
└── vendor/                     # 👥 Vendored upstream (hermes-webui fork)
```

> **`features/` vs `core/` vs `interfaces/`** — a feature is something you could
> switch off; `core/` is shared by several features; `interfaces/` is only ever
> *how someone connects* (a window, a terminal, a socket), never business logic.

---

## 💡 How Modular Features Work

Every feature in `jaeger_ai/features/` is designed to be **self-contained**:
1. **Its own code**: All scripts, endpoints, and logic live inside that feature's directory.
2. **Its own docs**: Contains a beginner-friendly `README.md` explaining what the feature does, how it works, and which files to edit.
3. **Its own tests/verification**: Contains verification scripts or unit test references.

Non-coders and developers can safely work inside a feature folder without worrying about breaking unrelated parts of the system.
