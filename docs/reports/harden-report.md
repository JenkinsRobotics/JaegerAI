# Jaeger production harden report

**Branch:** `finish-alpha`  
**Commit:** `fc7c243` — `harden(finance,ares,mac-ui): production gates, session paths, fail-closed cognition`  
**When:** 2026-09-11 ~01:02 PT  
**Machine:** MatthewacStudio (`f9644398-ff83-41bc-94e8-7d0bca7aac5d`)  
**Stack after verification:** **STOPPED** (WebUI, adapters, bridge, desktop all down)

---

## What hardened

### A) Finance (`jaeger_ai/features/finance/`)
- Monarch session canonical path: `~/.jaeger/finance/mm_session.pickle` (or `$JAEGER_STATE_DIR` / `$JAEGER_HOME`).
- One-shot migrate from legacy `~/.ares/.mm_session.pickle` with clear log + `0600`.
- Typed errors: `MonarchError` / `MonarchSessionMissing` / `MonarchAPIError` / `MonarchDateError` / `MonarchImportError`.
- API timeouts via `asyncio.wait_for`; date bounds validated (`startDate`/`endDate`); fail-closed without session; secrets never logged (type-only).
- `FinanceWorker` persists reports **only** under `~/.jaeger/reports/finance/` (cap retained stamped files); bounded category/tx loops; API errors caught.
- `MonarchAuthSheet.swift`: honest copy — AutoFill is UI-only; session is local pickle 0600 — **not** Keychain AES-GCM; writes to `~/.jaeger/finance/`.

### B) ARES (`jaeger_ai/ares/`) — kept path, honest naming
- Module docstring: experimental endogenous heartbeat cognition — **NOT** AGI/SI; product/archive ARES (`~/.ares`) ≠ this module.
- `ARESConfig` defaults fail-closed: `allow_dangerous_system_actions=False`, `allow_notifications=False`, `allow_audio_play=False`.
- `SystemTransducer`: `run_test_suite` / code-mod actions blocked unless allow flag; `clean_scratch_caches` limited to `~/.jaeger/scratch`.
- Visual/acoustic: notifications/playback only if allowed.
- Honcho optional — tick never crashes if Honcho down; belief under `~/.jaeger/ares/`.
- Prefer keep `jaeger_ai/ares` (no rename churn).

### C) Mac UI (`ChatView.swift`)
- Chat / Avatar / Work nav retained.
- `PROJECTS` from `~/.jaeger/desktop/projects.json` with defaults **JaegerAI**, **Finances** (migrate once).
- PINNED: primary from agent `displayName`; Monarch pin kept.
- `AGENTS` section only when Gateway lists agents; gateway down → sessions-only (no fake Stack Auditor / Release Scribe / Grok Bot roster). Header comment cleaned.

---

## Tests

| Suite | Result |
|-------|--------|
| `pytest` finance + ares | **20 passed** |
| `swift build` (JaegerAI) | **PASS** |
| `swift test` (JaegerAITests) | **58 passed**, 2 skipped, 0 failures |
| `./jaeger status` after stop | **all stopped** |

---

## UI verification matrix (authorized temporary start)

Stack was started for verification via `scripts/verify-stack-smoke.py --start --chat-url http://100.74.2.15:8790/`, desktop launched, then **`jaeger stop`** restored stopped state.

### Smoke (`verify-stack-smoke.py`)
- **71 PASS**, **4 FAIL** (3 required): profile catalog only exposes `default` as a named profile (`jaeger`/`openclaw`/`roundtable` presence FAIL); cookie-scoped tab APIs still PASS for all four profile cookies. Hermes runtime :8787 WARN (down). Live LLM `--live` skipped.

### WebUI rail + composer (API per profile cookie @ `http://100.74.2.15:8790/`)

Legend: PASS = HTTP 2xx on backing API; FAIL = 4xx/timeout. Browser click automation not available in this agent (no browser MCP). Checklist companion: `scripts/verify-stack-ui-checklist.md`.

| Control | default | jaeger | openclaw | roundtable |
|---------|---------|--------|----------|------------|
| Chat (`/api/sessions`) | PASS | PASS | PASS | PASS |
| Tasks (`/api/crons`) | PASS | PASS | PASS | PASS |
| Kanban (`/api/kanban/boards`) | PASS | PASS* | PASS* | PASS* |
| Skills | PASS | PASS | PASS | PASS |
| Memory | PASS | PASS | PASS | PASS |
| Spaces | PASS | PASS | PASS | PASS |
| Agent profiles (`/api/profiles`) | PASS | PASS | PASS | PASS |
| Todos (`/api/todos`) | FAIL(404) | FAIL(404) | FAIL(404) | FAIL(404) |
| Insights | PASS | PASS | PASS | PASS |
| Logs | PASS | PASS | PASS | PASS |
| Settings | PASS | PASS | PASS | PASS |
| Models chip API | PASS | PASS | PASS | PASS |
| Gateway status | PASS | PASS | PASS | PASS |
| Health agent | PASS | PASS | PASS | PASS |
| Auth status | PASS | PASS | PASS | PASS |
| Profile active | PASS | PASS | PASS | PASS |
| Profile switch POST | FAIL(400)** | FAIL(400)** | FAIL(400)** | FAIL(400)** |

\* Kanban corrected to `/api/kanban/boards` (bare `/api/kanban` 404).  
\*\* Smoke used cookie-active fallback successfully for per-profile tab APIs despite switch POST 400 / profile-list gaps.

**Manual browser clicks not auto-run:** composer Attach/Mic/YOLO/Send, titlebar Reload, Kanban New task cancel, etc. — require human or Accessibility-enabled UI automation.

### Mac app

| Check | Result | Notes |
|-------|--------|-------|
| `swift build` | PASS | |
| `swift test` | PASS (58) | |
| App launch (`JaegerAI.app`) | PASS | `jaeger status` showed Desktop Running PID |
| Chat/Avatar/Work nav (code) | PASS | present in `ChatView` |
| Sidebar sessions / New Chat (code) | PASS | |
| projects.json wiring (code) | PASS | `DesktopProjectStore` |
| Gateway AGENTS gated (code) | PASS | no fake roster |
| Monarch sheet path/honesty (code) | PASS | |
| Work/Avatar stages (code) | PASS | |
| Suggestion chips / hero (code) | PASS | |
| osascript UI clicks | **BLOCKED** | System Events timed out — no Accessibility/TCC for agent; Monarch open/cancel, chip clicks, Work cards not auto-clicked |
| screencapture | UNAVAILABLE | `/usr/bin/screencapture` missing in this shell environment |

---

## Residuals
1. WebUI profile catalog still only lists `default` as first-class; other profiles work via cookie fallback — product gap, not introduced by this harden.
2. `/api/todos` 404 — Todos rail may be client-only or differently routed; confirm against live UI.
3. Mac UI click matrix incomplete without Accessibility permission for Cursor/agent `osascript`.
4. Gateway `:8810` was not started (plist missing / stopped); AGENTS sidebar will stay empty until gateway up.
5. Optional rename `jaeger_ai/ares` → `jaeger_ai/cognition/` deferred (docs honesty preferred over churn).
6. Live LLM WebUI send (`--live`) not run (token spend).

---

## Commits
- `fc7c243` harden(finance,ares,mac-ui): production gates, session paths, fail-closed cognition
