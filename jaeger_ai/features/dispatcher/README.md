# 📋 Jaeger Dispatcher Feature

> **Autonomous Task Coordination, Session Routing & Kanban Engine**  
> Enables Jaeger to manage primary operator conversations while delegating intensive batch work to autonomous background workers.

---

## 📖 What is the Dispatcher?

When working with an AI assistant, you often want to keep chatting in the main conversation while having heavy tasks (like audits, codebase refactoring, or research) run in the background.

The Dispatcher solves this by dividing responsibility into:
1. **The Primary Session**: The single persistent conversation between you and Jaeger.
2. **Worker Sessions**: Isolated, background workers (`delegate:<id>`) that run autonomous goal loops and report back summaries when finished.
3. **The Dispatcher Board**: A visual Kanban interface inside the Web UI where you can view running tasks, skills, and memory bindings.

---

## 📂 Folder Contents & Architecture

| File | What it does | When to edit it |
| :--- | :--- | :--- |
| **`store.py`** | SQLite database (`dispatcher.sqlite3`) tracking active goals, focus work, and task classifications. | Edit when adding new task categories (`coding`, `research`, `audit`) or changing how tasks are tracked. |
| **`router.py`** | Session key normalization and turn preparation (determining primary vs worker sessions). | Edit when changing how messages are routed to workers or how context is compacted. |
| **`sidecar.py`** | Token-authenticated HTTP sidecar (port 8646) that connects the Web UI Dispatcher panel to Jaeger. | Edit when exposing new endpoints or panel actions to the Web UI. |
| **`static/jaeger_dispatcher.js`** | The frontend JavaScript extension rendering the Dispatcher Kanban board in the Web UI. | Edit when customizing the Dispatcher UI layout, styling, or buttons in the browser. |
| **`verify.py`** | Verification script testing end-to-end task dispatching and continuity. | Run to ensure background workers and session state are functioning. |

---

## 💡 Note on CLI Verbs vs. Runtime Dispatcher

In Jaeger, there are two different concepts often called "dispatch":
* **CLI Command Dispatcher** (`jaeger_ai/cli/verbs/dispatch.py`): Parses command-line arguments (like `jaeger start`, `jaeger stop`, `jaeger status`) and routes them to CLI handlers.
* **Runtime Task Dispatcher** (this folder `jaeger_ai/features/dispatcher/`): Coordinates background workers, Kanban tasks, and autonomous execution.

---

## 🚀 How to Test the Dispatcher

### Run the Dispatcher Test Suite
```bash
pytest dev/tests/jaeger_ai/interfaces/test_dispatcher.py dev/tests/jaeger_ai/core/test_dispatch.py
```
