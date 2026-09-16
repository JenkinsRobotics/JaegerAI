# 🌐 Jaeger Web UI Feature

> **Home for the Jaeger Web Interface**  
> The complete browser application, API, runtime adapter, profile manager, and
> session unifier live here. This directory is the single implementation home
> for JaegerAI's WebUI.

---

## 📖 What is the Web UI?

Jaeger's Web UI provides a browser-based interface for chatting with agents, selecting workspaces, managing profiles (Jaeger, Roundtable, OpenClaw), and monitoring background runs.

It connects:
1. **Frontend**: Jaeger-branded WebUI on port **8790** (chat UI, settings, Kanban).
2. **Adapter**: Loopback runner on port **8791** bridging browser API requests into native Jaeger agents.
3. **Profiles**: Hermes Agent, Jaeger AI, OpenClaw, and Roundtable profiles with isolated sessions and independent runtime capabilities.
4. **Hermes Agent**: Its authenticated native API runs separately on loopback port **8645**. It is an agent runtime, not another browser UI.

---

## 📂 Folder Contents & Architecture

| Folder / File | What it does | When to edit it |
| :--- | :--- | :--- |
| **`server.py`** | First-party WebUI HTTP server and SSE host. | Edit when changing server startup or request handling. |
| **`api/`** | Browser API, session store, profile operations, streaming and Jaeger gateway projections. | Edit when changing browser-visible behavior or persistence. |
| **`static/`** | Browser HTML, JavaScript, CSS, icons and localizations. | Edit when changing the browser experience. |
| **`adapter/server.py`** | The HTTP adapter server handling incoming Web UI REST/SSE requests. | Edit when adding or modifying API endpoints between the browser and Jaeger. |
| **`adapter/bridge_client.py`** | Client communication between the adapter and Jaeger's core bridge. | Edit when changing low-level communication protocols. |
| **`service/service.py`** | Background service lifecycle manager (starting, stopping, and monitoring the Web UI process). | Edit when changing port bindings, health checks, or restart behavior. |
| **`service/profile_layout.py`** | Sets up profile configurations, workspaces, and model catalogs. | Edit when adding new workspaces or updating default models. |
| **`service/session_unify.py`** | Keeps session histories synchronized across agent profiles. | Edit when altering how session databases are merged or cleaned up. |

### Files this feature owns, but that live outside this folder

These are **not** duplicated here. The paths below are the only copies; editing
anything else will not change what the browser loads.

| File | What it does | Why it lives there |
| :--- | :--- | :--- |
| **`jaeger_ai/assets/jaeger_webui_branding.js`** | Frontend branding + the Agents roster (app title, logo, colors, framework switching). | `jaeger_ai/assets/` is the single directory mounted into the WebUI as its extension folder (`HERMES_WEBUI_EXTENSION_DIR`). Three features ship scripts into that one mount, so the mount — not the feature — owns the directory. |
| **`jaeger_ai/assets/jaeger_webui_extensions.json`** | Registers which extension scripts the WebUI loads. | Same mount as above; it is the manifest for that directory. |
| **`scripts/run-jaeger-webui.sh`** | Boots the Web UI locally (port 8790). | Sits with the other operator entry-point scripts. |
| **`jaeger_ai/core/frameworks/`** | Per-framework execution: Hermes, OpenClaw and Roundtable turn-running. | Historical split. `adapter/profile_runner.py` imports from here. |

The browser source descends from Hermes WebUI. Its license is preserved in
`HERMES_WEBUI_LICENSE`; JaegerAI now owns this integrated implementation and
does not load it from a submodule or container overlay.

---

## 🚀 How to Start and Test the Web UI

### 1. From the Command Line
```bash
# Start the full Jaeger stack (including Web UI)
jaeger start

# Or launch only the Web UI
jaeger webui
```

### 2. View in Browser
Open the Tailscale chat URL from `jaeger webui url` (this Mac:
[http://100.74.2.15:8790/](http://100.74.2.15:8790/)). Loopback
`http://127.0.0.1:8790/` is a local probe only.

### 3. Run Automated Tests
```bash
pytest dev/tests/jaeger_ai/features/webui/
```
