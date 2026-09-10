# 🌐 Jaeger Web UI Feature

> **Unified Home for the Jaeger Web Interface**  
> Consolidates the web server adapter, profile manager, session unifier, custom branding, and startup scripts into a single self-contained directory.

---

## 📖 What is the Web UI?

Jaeger's Web UI provides a browser-based interface for chatting with agents, selecting workspaces, managing profiles (Jaeger, Roundtable, OpenClaw), and monitoring background runs.

It connects:
1. **Frontend**: The web application (running on port 8642) displaying the chat UI, settings, and Kanban boards.
2. **Adapter**: A loopback server bridging browser API requests into native Jaeger agents.
3. **Profiles**: Different personality profiles (`jaeger`, `roundtable`, `openclaw`) with independent models and tool capabilities.

---

## 📂 Folder Contents & Architecture

| Folder / File | What it does | When to edit it |
| :--- | :--- | :--- |
| **`adapter/server.py`** | The HTTP adapter server handling incoming Web UI REST/SSE requests. | Edit when adding or modifying API endpoints between the browser and Jaeger. |
| **`adapter/bridge_client.py`** | Client communication between the adapter and Jaeger's core bridge. | Edit when changing low-level communication protocols. |
| **`service/service.py`** | Background service lifecycle manager (starting, stopping, and monitoring the Web UI process). | Edit when changing port bindings, health checks, or restart behavior. |
| **`service/profile_layout.py`** | Sets up profile configurations, workspaces, and model catalogs. | Edit when adding new workspaces or updating default models. |
| **`service/session_unify.py`** | Keeps session histories synchronized across agent profiles. | Edit when altering how session databases are merged or cleaned up. |
| **`static/jaeger_webui_branding.js`** | Frontend branding injection (app title, header logo, colors). | Edit to customize colors, titles, or browser behavior. |
| **`static/jaeger_webui_extensions.json`**| Configuration for registered UI extensions (like the Dispatcher board). | Edit to add or remove custom panels in the Web UI. |
| **`scripts/run_webui.sh`** | Shell script to boot the Web UI locally. | Run to start the Web UI manually. |
| **`scripts/prepare_webui.py`** | Setup script ensuring dependencies and profiles are initialized. | Run during installation or setup. |

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
Open: [http://127.0.0.1:8642](http://127.0.0.1:8642)

### 3. Run Automated Tests
```bash
pytest dev/tests/jaeger_ai/features/hermes_webui/
```
